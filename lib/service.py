import os
import time
import copy
import json
import yaml
import requests
import functools
import traceback

import redis
import flask
import flask_restful
import sqlalchemy.exc

import opengui
import pykube

import mysql

def app():

    app = flask.Flask("nandy-io-speech-api")

    app.kube = None

    app.mysql = mysql.MySQL()

    app.redis = redis.StrictRedis(host=os.environ['REDIS_HOST'], port=int(os.environ['REDIS_PORT']))
    app.channel = os.environ['REDIS_CHANNEL']

    if os.path.exists("/opt/nandy-io/secret/config"):
        app.kube = pykube.HTTPClient(pykube.KubeConfig.from_file("/opt/nandy-io/secret/config"))
    else:
        app.kube = pykube.HTTPClient(pykube.KubeConfig.from_service_account())

    api = flask_restful.Api(app)

    api.add_resource(Health, '/health')
    api.add_resource(PersonCL, '/person')
    api.add_resource(PersonRUD, '/person/<int:id>')
    api.add_resource(AreaCL, '/area')
    api.add_resource(AreaRUD, '/area/<int:id>')
    api.add_resource(TemplateCL, '/template')
    api.add_resource(TemplateRUD, '/template/<int:id>')
    api.add_resource(RoutineCL, '/routine')
    api.add_resource(RoutineRUD, '/routine/<int:id>')
    api.add_resource(RoutineAction, '/routine/<int:routine_id>/<action>')
    api.add_resource(TaskAction, '/routine/<int:routine_id>/task/<int:task_id>/<action>')
    api.add_resource(ToDoCL, '/todo')
    api.add_resource(ToDoRUD, '/todo/<int:id>')
    api.add_resource(ActCL, '/act')
    api.add_resource(ActRUD, '/act/<int:id>')

    return app


def require_session(endpoint):
    @functools.wraps(endpoint)
    def wrap(*args, **kwargs):

        flask.request.session = flask.current_app.mysql.session()

        try:

            response = endpoint(*args, **kwargs)

        except sqlalchemy.exc.InvalidRequestError:

            response = flask.make_response(json.dumps({
                "message": "session error",
                "traceback": traceback.format_exc()
            }))
            response.headers.set('Content-Type', 'application/json')
            response.status_code = 500

            flask.request.session.rollback()

        except Exception as exception:

            response = flask.make_response(json.dumps({"message": str(exception)}))
            response.headers.set('Content-Type', 'application/json')
            response.status_code = 500

        flask.request.session.close()

        return response

    return wrap


# These are for sending and recieving model data as dicts

def model_in(converted):

    fields = {}

    for field in converted.keys():

        if field == "yaml":
            fields["data"] = yaml.safe_load(converted[field])
        else:
            fields[field] = converted[field]

    return fields

def model_out(model):

    converted = {}

    for field in model.__table__.columns._data.keys():

        converted[field] = getattr(model, field)

        if field == "data":
            converted["yaml"] = yaml.safe_dump(dict(converted[field]), default_flow_style=False)

    return converted

def models_out(models):

    return [model_out(model) for model in models]


def notify(message):

    flask.current_app.redis.publish(flask.current_app.channel, json.dumps(message))


class Health(flask_restful.Resource):
    def get(self):
        return {"message": "OK"}


class BaseCL(flask_restful.Resource):

    @require_session
    def post(self):

        item = self.Model(**model_in(flask.request.json[self.singular]))
        flask.request.session.add(item)
        flask.request.session.commit()

        return {self.singular: model_out(item)}, 201

    @require_session
    def get(self):

        items = flask.request.session.query(
            self.Model
        ).filter_by(
            **flask.request.args.to_dict()
        ).order_by(
            *self.order_by
        ).all()
        flask.request.session.commit()

        return {self.plural: models_out(items)}

class BaseRUD(flask_restful.Resource):

    @require_session
    def get(self, id):

        item = flask.request.session.query(
            self.Model
        ).get(
            id
        )
        flask.request.session.commit()

        return {self.singular: model_out(item)}

    @require_session
    def patch(self, id):

        rows = flask.request.session.query(
            self.Model
        ).filter_by(
            id=id
        ).update(
            model_in(flask.request.json[self.singular])
        )
        flask.request.session.commit()

        return {"updated": rows}, 202

    @require_session
    def delete(self, id):

        rows = flask.request.session.query(
            self.Model
        ).filter_by(
            id=id
        ).delete()
        flask.request.session.commit()

        return {"deleted": rows}, 202

class Person:
    singular = "person"
    plural = "persons"
    Model = mysql.Person
    order_by = [mysql.Person.name]

class PersonCL(Person, BaseCL):
    pass

class PersonRUD(Person, BaseRUD):
    pass


class Area:
    singular = "area"
    plural = "areas"
    Model = mysql.Area
    order_by = [mysql.Area.name]

class AreaCL(Area, BaseCL):
    pass

class AreaRUD(Area, BaseRUD):
    pass


class Template:
    singular = "template"
    plural = "templates"
    Model = mysql.Template
    order_by = [mysql.Template.name]

class TemplateCL(Template, BaseCL):
    pass

class TemplateRUD(Template, BaseRUD):
    pass


class Routine:
    singular = "routine"
    plural = "routines"
    Model = mysql.Routine
    order_by = [mysql.Routine.created.desc()]

class RoutineAction(flask_restful.Resource):

    @staticmethod
    def build(**kwargs):
        """
        Builds a routine from a raw fields, template, template id, etc.
        """

        fields = {
            "status": "started",
            "created": time.time(),
            "data": {}
        }

        template = {}

        if "template" in kwargs:
            template = kwargs["template"]
        elif "template_id" in kwargs:
            template = flask.request.session.query(
                mysql.Template
            ).get(
                kwargs["template_id"]
            ).data

        if template:
            fields["data"].update(copy.deepcopy(template))
        
        if "data" in kwargs:
            fields["data"].update(copy.deepcopy(kwargs["data"]))

        if "email" in kwargs:
            fields["person_id"] = flask.request.session.query(
                mysql.Person
            ).filter_by(
                email=kwargs["email"]
            ).one().id
        elif "person" in template:
            fields["person_id"] = flask.request.session.query(
                mysql.Person
            ).filter_by(
                name=template["person"]
            ).one().id

        for field in ["name", "person_id", "status", "created", "updated"]:
            if field in kwargs:
                fields[field] = kwargs[field]

        if "updated" not in fields:
            fields["updated"] =  fields["created"]

        if "language" not in fields["data"]:
            fields["data"]["language"] = "en-us"

        if "tasks" in fields["data"]:
            for index, task in enumerate(fields["data"]["tasks"]):
                if "id" not in task:
                    task["id"] = index

        return fields

    @staticmethod
    def notify(action, routine):
        """
        Notifies somethign happened
        """

        routine.data["notified"] = time.time()
        routine.updated = time.time()

        notify({
            "kind": "routine",
            "action": action,
            "routine": model_out(routine),
            "person": model_out(routine.person)
        })

    @classmethod
    def check(cls, routine):
        """
        Checks to see if there's tasks remaining, if so, starts one.
        If not completes the task
        """

        if "tasks" not in routine.data:
            return

        # Go through all the tasks

        for task in routine.data["tasks"]:

            # If there's one that's start and not completed, we're good

            if "start" in task and "end" not in task:
                return

        # Go through the tasks again now that we know none are in progress 

        for task in routine.data["tasks"]:

            # If not start, start it, and let 'em know

            if "start" not in task:
                task["start"] = time.time()

                if "paused" in task and task["paused"]:
                    TaskAction.notify("pause", task, routine)
                else:
                    TaskAction.notify("start", task, routine)

                return

        # If we're here, all are done, so complete the routine

        cls.complete(routine)

    @classmethod
    def start(cls, routine):
        """
        Starts a routine
        """

        cls.notify("start", routine)
        cls.check(routine)

    @classmethod
    def create(cls, **kwargs):

        routine = mysql.Routine(**cls.build(**kwargs))
        flask.request.session.add(routine)
        flask.request.session.commit()

        cls.start(routine)
        flask.request.session.commit()

        return routine

    @classmethod
    def next(cls, routine):
        """
        Completes the current task and starts the next. This is used
        with a button press.  
        """

        # Go through all the tasks, complete the first one found
        # that's ongoing and break

        for task in routine.data["tasks"]:
            if "start" in task and "end" not in task:
                TaskAction.complete(task, routine)
                return True

        return False

    @classmethod
    def remind(cls, routine):
        """
        Reminds a routine
        """

        cls.notify("remind", routine)

        return True

    @classmethod
    def pause(cls, routine):
        """
        Pauses a routine
        """

        # Pause if it isn't. 

        if "paused" not in routine.data or not routine.data["paused"]:

            routine.data["paused"] = True
            cls.notify("pause", routine)

            return True

        return False

    @classmethod
    def unpause(cls, routine):
        """
        Resumes a routine
        """

        # Resume if it's paused

        if "paused" in routine.data and routine.data["paused"]:

            routine.data["paused"] = False
            cls.notify("unpause", routine)

            return True

        return False

    @classmethod
    def skip(cls, routine):
        """
        Skips a routine
        """

        # Skip if it hasn't been

        if "skipped" not in routine.data or not routine.data["skipped"]:

            routine.data["skipped"] = True
            routine.data["end"] = time.time()
            routine.status = "ended"
            cls.notify("skip", routine)

            return True

        return False

    @classmethod
    def unskip(cls, routine):
        """
        Unskips a routine
        """

        # Unskip if it has been

        if "skipped" in routine.data and routine.data["skipped"]:

            routine.data["skipped"] = False
            del routine.data["end"]
            routine.status = "started"
            cls.notify("unskip", routine)

            return True

        return False

    @classmethod
    def complete(cls, routine):
        """
        Completes a routine
        """

        if "end" not in routine.data or routine.status != "ended":

            routine.data["end"] = time.time()
            routine.status = "ended"
            cls.notify("complete", routine)

            return True

        return False

    @classmethod
    def uncomplete(cls, routine):
        """
        Uncompletes a routine
        """

        if "end" in routine.data or routine.status == "ended":

            del routine.data["end"]
            routine.status = "started"
            cls.notify("uncomplete", routine)

            return True
        
        return False

    @classmethod
    def expire(cls, routine):
        """
        Skips a routine
        """

        # Skip if it hasn't been

        if "expired" not in routine.data or not routine.data["expired"]:

            routine.data["expired"] = True
            routine.data["end"] = time.time()
            routine.status = "ended"
            cls.notify("expire", routine)

            return True

        return False

    @classmethod
    def unexpire(cls, routine):
        """
        Unexpires a routine
        """

        # Unexpire if it has been

        if "expired" in routine.data and routine.data["expired"]:

            routine.data["expired"] = False
            del routine.data["end"]
            routine.status = "started"
            cls.notify("unexpire", routine)

            return True

        return False

    @require_session
    def patch(self, routine_id, action):

        routine = flask.request.session.query(mysql.Routine).get(routine_id)

        if action in ["next", "remind", "pause", "unpause", "skip", "unskip", "complete", "uncomplete", "expire", "unexpire"]:

            updated = getattr(self, action)(routine)

            if updated:
                flask.request.session.commit()

            return {"updated": updated}, 202


class TaskAction(flask_restful.Resource):

    @staticmethod
    def notify(action, task, routine):
        """
        Notifies somethign happened
        """

        routine.data["notified"] = time.time()
        routine.updated = time.time()
        task["notified"] = time.time() 

        notify({
            "kind": "task",
            "action": action,
            "task": task,
            "routine": model_out(routine),
            "person": model_out(routine.person)
        })

    @classmethod
    def remind(cls, task, routine):
        """
        Reminds a task
        """

        cls.notify("remind", task, routine)

        return True

    @classmethod
    def pause(cls, task, routine):
        """
        Pauses a task
        """

        # Pause if it isn't. 

        if "paused" not in task or not task["paused"]:

            task["paused"] = True
            cls.notify("pause", task, routine)

            return True

        return False

    @classmethod
    def unpause(cls, task, routine):
        """
        Resumes a task
        """

        # Resume if it's paused

        if "paused" in task and task["paused"]:

            task["paused"] = False
            cls.notify("unpause", task, routine)

            return True

        return False

    @classmethod
    def skip(cls, task, routine):
        """
        Skips a task
        """

        # Pause if it hasn't been

        if "skipped" not in task or not task["skipped"]:

            task["skipped"] = True
            task["end"] = time.time()

            # If it hasn't been started, do so now

            if "start" not in task:
                task["start"] = task["end"]
                
            cls.notify("skip", task, routine)

            # Check to see if there's another one and set

            RoutineAction.check(routine)

            return True

        return False

    @classmethod
    def unskip(cls, task, routine):
        """
        Unskips a task
        """

        # Unskip if has been

        if "skipped" in task and task["skipped"]:

            task["skipped"] = False
            del task["end"]
            cls.notify("unskip", task, routine)

            # Incomplete the overall Routine (if necessary)

            RoutineAction.uncomplete(routine)

            return True

        return False

    @classmethod
    def complete(cls, task, routine):
        """
        Completes a specific task
        """

        # Complete if it isn't. 

        if "end" not in task:

            task["end"] = time.time()

            # If it hasn't been started, do so now

            if "start" not in task:
                task["start"] = task["end"]

            cls.notify("complete", task, routine)

            # See if there's a next one

            RoutineAction.check(routine)

            return True

        return False

    @classmethod
    def uncomplete(cls, task, routine):
        """
        Undoes a specific task
        """

        # Delete completed from the task.  This'll leave the current task started.
        # It's either that or restart it.  This action is done if a kid said they
        # were done when they weren't.  So an extra penality is fine. 

        if "end" in task:
    
            del task["end"]
            cls.notify("uncomplete", task, routine)

            # Incomplete the overall Routine (if necessary)

            RoutineAction.uncomplete(routine)

            return True

        return False

    @require_session
    def patch(self, routine_id, task_id, action):

        routine = flask.request.session.query(mysql.Routine).get(routine_id)
        task = routine.data["tasks"][task_id]

        if action in ["remind", "pause", "unpause", "skip", "unskip", "complete", "uncomplete"]:

            updated = getattr(self, action)(task, routine)

            if updated:
                flask.request.session.commit()

            return {"updated": updated}, 202

class RoutineCL(Routine, BaseCL):

    @require_session
    def post(self):

        item = RoutineAction.create(**model_in(flask.request.json[self.singular]))

        return {self.singular: model_out(item)}, 201

class RoutineRUD(Routine, BaseRUD):
    pass

class ToDo:
    singular = "todo"
    plural = "todos"
    Model = mysql.ToDo
    order_by = [mysql.ToDo.created.desc()]

class ToDoCL(ToDo, BaseCL):
    pass

class ToDoRUD(ToDo, BaseRUD):
    pass


class Act:
    singular = "act"
    plural = "acts"
    Model = mysql.Act
    order_by = [mysql.Act.created.desc()]

class ActCL(Act, BaseCL):
    pass

class ActRUD(Act, BaseRUD):
    pass
