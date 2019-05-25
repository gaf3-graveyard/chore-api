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

    app.mysql = mysql.MySQL()

    app.redis = redis.StrictRedis(host=os.environ['REDIS_HOST'], port=int(os.environ['REDIS_PORT']))
    app.channel = os.environ['REDIS_CHANNEL']

    if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"):
        app.kube = pykube.HTTPClient(pykube.KubeConfig.from_service_account())
    else:
        app.kube = pykube.HTTPClient(pykube.KubeConfig.from_url("http://host.docker.internal:7580"))

    api = flask_restful.Api(app)

    api.add_resource(Health, '/health')
    api.add_resource(PersonCL, '/person')
    api.add_resource(PersonRUD, '/person/<int:id>')
    api.add_resource(TemplateCL, '/template')
    api.add_resource(TemplateRUD, '/template/<int:id>')
    api.add_resource(AreaCL, '/area')
    api.add_resource(AreaRUD, '/area/<int:id>')
    api.add_resource(AreaValue, '/area/<int:id>/<action>')
    api.add_resource(ActCL, '/act')
    api.add_resource(ActRUD, '/act/<int:id>')
    api.add_resource(ActValue, '/act/<int:id>/<action>')
    api.add_resource(ToDoCL, '/todo')
    api.add_resource(ToDoRUD, '/todo/<int:id>')
    api.add_resource(ToDoAction, '/todo/<int:id>/<action>')
    api.add_resource(RoutineCL, '/routine')
    api.add_resource(RoutineRUD, '/routine/<int:id>')
    api.add_resource(RoutineAction, '/routine/<int:id>/<action>')
    api.add_resource(TaskAction, '/routine/<int:routine_id>/task/<int:task_id>/<action>')


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

        model = self.Model(**model_in(flask.request.json[self.singular]))
        flask.request.session.add(model)
        flask.request.session.commit()

        return {self.singular: model_out(model)}, 201

    @require_session
    def get(self):

        models = flask.request.session.query(
            self.Model
        ).filter_by(
            **flask.request.args.to_dict()
        ).order_by(
            *self.order_by
        ).all()
        flask.request.session.commit()

        return {self.plural: models_out(models)}

class BaseRUD(flask_restful.Resource):

    @require_session
    def get(self, id):

        model = flask.request.session.query(
            self.Model
        ).get(
            id
        )
        flask.request.session.commit()

        return {self.singular: model_out(model)}

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


class Template:
    singular = "template"
    plural = "templates"
    Model = mysql.Template
    order_by = [mysql.Template.name]

class TemplateCL(Template, BaseCL):
    pass

class TemplateRUD(Template, BaseRUD):
    pass


class BaseStatus(flask_restful.Resource):

    @staticmethod
    def build(**kwargs):
        """
        Builds complete fields from a raw fields, template, template id, etc.
        """

        fields = {
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

        person = None

        if "person" in fields["data"]:
            fields["person_id"] = flask.request.session.query(
                mysql.Person
            ).filter_by(
                name=fields["data"]["person"]
            ).one().id

        for field in ["person_id", "name", "status", "created", "updated"]:
            if field in kwargs:
                fields[field] = kwargs[field]
            elif field in fields["data"]:
                fields[field] = fields["data"][field]

        return fields

    @classmethod
    def notify(cls, action, model):
        """
        Notifies somethign happened
        """

        model.data["notified"] = time.time()
        model.updated = time.time()

        notify({
            "kind": cls.singular,
            "action": action,
            cls.singular: model_out(model),
            "person": model_out(model.person)
        })

    @classmethod
    def create(cls, **kwargs):

        model = cls.Model(**cls.build(**kwargs))
        flask.request.session.add(model)
        flask.request.session.commit()

        cls.notify("create", model)

        return model

    @require_session
    def patch(self, id, action):

        model = flask.request.session.query(self.Model).get(id)

        if action in self.ACTIONS:

            updated = getattr(self, action)(model)

            if updated:
                flask.request.session.commit()

            return {"updated": updated}, 202


class BaseValue(BaseStatus):

    ACTIONS = ["right", "wrong"]

    @classmethod
    def wrong(cls, model):
        """
        Wrongs a model
        """

        if model.status == "positive":

            model.status = "negative"
            cls.notify("wrong", model)

            return True

        return False

    @classmethod
    def right(cls, model):
        """
        Rights a model
        """

        if model.status == "negative":

            model.status = "positive"
            cls.notify("right", model)

            return True

        return False


class BaseAction(BaseStatus):

    ACTIONS = ["remind", "pause", "unpause", "skip", "unskip", "complete", "uncomplete", "expire", "unexpire"]

    @classmethod
    def remind(cls, model):
        """
        Reminds a model
        """

        cls.notify("remind", model)

        return True

    @classmethod
    def pause(cls, model):
        """
        Pauses a model
        """

        if "paused" not in model.data or not model.data["paused"]:

            model.data["paused"] = True
            cls.notify("pause", model)

            return True

        return False

    @classmethod
    def unpause(cls, model):
        """
        Resumes a model
        """

        if "paused" in model.data and model.data["paused"]:

            model.data["paused"] = False
            cls.notify("unpause", model)

            return True

        return False

    @classmethod
    def skip(cls, model):
        """
        Skips a model
        """

        if "skipped" not in model.data or not model.data["skipped"]:

            model.data["skipped"] = True
            model.data["end"] = time.time()
            model.status = "closed"
            cls.notify("skip", model)

            return True

        return False

    @classmethod
    def unskip(cls, model):
        """
        Unskips a model
        """

        if "skipped" in model.data and model.data["skipped"]:

            model.data["skipped"] = False
            del model.data["end"]
            model.status = "opened"
            cls.notify("unskip", model)

            return True

        return False

    @classmethod
    def complete(cls, model):
        """
        Completes a model
        """

        if "end" not in model.data or model.status != "closed":

            model.data["end"] = time.time()
            model.status = "closed"
            cls.notify("complete", model)

            return True

        return False

    @classmethod
    def uncomplete(cls, model):
        """
        Uncompletes a model
        """

        if "end" in model.data or model.status == "closed":

            del model.data["end"]
            model.status = "opened"
            cls.notify("uncomplete", model)

            return True
        
        return False

    @classmethod
    def expire(cls, model):
        """
        Skips a model
        """

        if "expired" not in model.data or not model.data["expired"]:

            model.data["expired"] = True
            model.data["end"] = time.time()
            model.status = "closed"
            cls.notify("expire", model)

            return True

        return False

    @classmethod
    def unexpire(cls, model):
        """
        Unexpires a model
        """

        if "expired" in model.data and model.data["expired"]:

            model.data["expired"] = False
            del model.data["end"]
            model.status = "opened"
            cls.notify("unexpire", model)

            return True

        return False


class StatusCL(BaseStatus, BaseCL):

    @require_session
    def post(self):

        model = self.create(**model_in(flask.request.json[self.singular]))

        return {self.singular: model_out(model)}, 201


class Area:
    singular = "area"
    plural = "areas"
    Model = mysql.Area
    order_by = [mysql.Area.name]

class AreaCL(Area, StatusCL):
    pass

class AreaRUD(Area, BaseRUD):
    pass

class AreaValue(Area, BaseValue):

    @classmethod
    def wrong(cls, model):
        """
        Wrongs a model
        """

        if model.status == "positive":

            model.status = "negative"
            cls.notify("wrong", model)

            if "todo" in model.data:
                ToDoAction.create(person_id=model.person.id, data={"area": model.id}, template=model.data["todo"])

            return True

        return False


class Act:
    singular = "act"
    plural = "acts"
    Model = mysql.Act
    order_by = [mysql.Act.created.desc()]

class ActCL(Act, StatusCL):
    pass

class ActRUD(Act, BaseRUD):
    pass

class ActValue(Act, BaseValue):

    @classmethod
    def create(cls, **kwargs):

        model = cls.Model(**cls.build(**kwargs))
        flask.request.session.add(model)
        flask.request.session.commit()

        cls.notify("create", model)

        if model.status == "negative" and "todo" in model.data:
            ToDoAction.create(person_id=model.person.id, template=model.data["todo"])

        return model


class ToDo:
    singular = "todo"
    plural = "todos"
    Model = mysql.ToDo
    order_by = [mysql.ToDo.created.desc()]

class ToDoCL(ToDo, StatusCL):

    @require_session
    def patch(self):

        updated = ToDoAction.todos(flask.request.json["todos"])

        if updated:
            flask.request.session.commit()

        return {"updated": updated}, 202

class ToDoRUD(ToDo, BaseRUD):
    pass

class ToDoAction(ToDo, BaseAction):

    @staticmethod
    def todos(data):
        """
        Reminds all ToDos
        """

        if "person" in data:
            person_id = flask.request.session.query(
                mysql.Person
            ).filter_by(
                name=data["person"]
            ).one().id
        else:
            person_id = data["person_id"]

        person = flask.request.session.query(mysql.Person).get(person_id)

        updated = False

        todos = []

        for todo in flask.request.session.query(
            mysql.ToDo
        ).filter_by(
            person_id=person_id,
            status="opened"
        ).order_by(
            *ToDo.order_by
        ).all():

            todo.data["notified"] = time.time()
            todo.updated = time.time()
            todos.append(todo)

        if todos:

            notify({
                "kind": "todos",
                "action": "remind",
                "person": model_out(person),
                "speech": data.get("speech", {}),
                "todos": models_out(todos)
            })

            flask.request.session.commit()

            updated = True

        return updated

    @classmethod
    def complete(cls, model):
        """
        Completes a model
        """

        if "end" not in model.data or model.status != "closed":

            model.data["end"] = time.time()
            model.status = "closed"
            cls.notify("complete", model)

            if "area" in model.data:
                AreaValue.right(flask.request.session.query(mysql.Area).get(model.data["area"]))

            if "act" in model.data:
                ActValue.create(person_id=model.person.id, status="positive", template=model.data["act"])

            return True

        return False


class Routine:
    singular = "routine"
    plural = "routines"
    Model = mysql.Routine
    order_by = [mysql.Routine.created.desc()]

class RoutineCL(Routine, StatusCL):
    pass

class RoutineRUD(Routine, BaseRUD):
    pass

class RoutineAction(Routine, BaseAction):

    ACTIONS = ["remind", "next", "pause", "unpause", "skip", "unskip", "complete", "uncomplete", "expire", "unexpire"]

    @staticmethod
    def build(**kwargs):
        """
        Builds a routine from a raw fields, template, template id, etc.
        """

        fields = BaseAction.build(**kwargs)

        if fields["data"].get("todos"):

            tasks = []

            for todo in flask.request.session.query(
                mysql.ToDo
            ).filter_by(
                person_id=fields["person_id"],
                status="opened"
            ).order_by(
                *ToDo.order_by
            ).all():
                tasks.append({
                    "text": todo.data["text"],
                    "todo": todo.id
                })

            if "tasks" in fields["data"]:
                tasks.extend(fields["data"]["tasks"])
            
            fields["data"]["tasks"] = tasks

        if "tasks" in fields["data"]:

            for index, task in enumerate(fields["data"]["tasks"]):
                if "id" not in task:
                    task["id"] = index

        return fields

    @classmethod
    def check(cls, routine):
        """
        Checks to see if there's tasks remaining, if so, starts one.
        If not completes the task
        """

        if "tasks" not in routine.data:
            return

        for task in routine.data["tasks"]:

            if "start" in task and "end" not in task:
                return

        for task in routine.data["tasks"]:

            if "start" not in task:
                task["start"] = time.time()

                if "paused" in task and task["paused"]:
                    TaskAction.notify("pause", task, routine)
                else:
                    TaskAction.notify("start", task, routine)

                return

        cls.complete(routine)

    @classmethod
    def create(cls, **kwargs):

        model = cls.Model(**cls.build(**kwargs))
        flask.request.session.add(model)
        flask.request.session.commit()

        model.data["start"] = time.time()
        cls.notify("create", model)

        cls.check(model)
        flask.request.session.commit()

        return model

    @classmethod
    def next(cls, routine):
        """
        Completes the current task and starts the next. This is used
        with a button press.  
        """

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

        if "skipped" not in task or not task["skipped"]:

            task["skipped"] = True
            task["end"] = time.time()

            if "start" not in task:
                task["start"] = task["end"]
                
            cls.notify("skip", task, routine)

            RoutineAction.check(routine)

            return True

        return False

    @classmethod
    def unskip(cls, task, routine):
        """
        Unskips a task
        """

        if "skipped" in task and task["skipped"]:

            task["skipped"] = False
            del task["end"]
            cls.notify("unskip", task, routine)

            RoutineAction.uncomplete(routine)

            return True

        return False

    @classmethod
    def complete(cls, task, routine):
        """
        Completes a specific task
        """

        if "end" not in task:

            task["end"] = time.time()

            if "start" not in task:
                task["start"] = task["end"]

            cls.notify("complete", task, routine)

            RoutineAction.check(routine)

            if "todo" in task:
                ToDoAction.complete(flask.request.session.query(mysql.ToDo).get(task["todo"]))

            return True

        return False

    @classmethod
    def uncomplete(cls, task, routine):
        """
        Undoes a specific task
        """

        if "end" in task:
    
            del task["end"]
            cls.notify("uncomplete", task, routine)

            RoutineAction.uncomplete(routine)

            if "todo" in task:
                ToDoAction.uncomplete(flask.request.session.query(mysql.ToDo).get(task["todo"]))

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
