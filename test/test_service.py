import unittest
import unittest.mock

import os
import json
import yaml

import flask
import sqlalchemy.exc

import mysql
import test_mysql

import service

class MockRedis(object):

    def __init__(self, host, port):

        self.host = host
        self.port = port
        self.channel = None

        self.messages = []

    def publish(self, channel, message):

        self.channel = channel
        self.messages.append(message)

class TestBase(unittest.TestCase):

    maxDiff = None

    @classmethod
    @unittest.mock.patch.dict(os.environ, {
        "REDIS_HOST": "most.com",
        "REDIS_PORT": "667",
        "REDIS_CHANNEL": "stuff"
    })
    @unittest.mock.patch("redis.StrictRedis", MockRedis)
    @unittest.mock.patch("pykube.HTTPClient", unittest.mock.MagicMock)
    @unittest.mock.patch("pykube.KubeConfig.from_service_account", unittest.mock.MagicMock)
    def setUpClass(cls):

        cls.app = service.app()
        cls.api = cls.app.test_client()

    def setUp(self):

        mysql.drop_database()
        mysql.create_database()

        self.session = self.app.mysql.session()
        self.sample = test_mysql.Sample(self.session)

        mysql.Base.metadata.create_all(self.app.mysql.engine)

    def tearDown(self):

        self.session.close()
        mysql.drop_database()

    def assertStatusValue(self, response, code, key, value):

        self.assertEqual(response.status_code, code, response.json)
        self.assertEqual(response.json[key], value)

    def assertStatusModel(self, response, code, key, model):

        self.assertEqual(response.status_code, code, response.json)

        for field in model:
            self.assertEqual(response.json[key][field], model[field], field)

    def assertStatusModels(self, response, code, key, mysql):

        self.assertEqual(response.status_code, code, response.json)

        for index, model in enumerate(mysql):
            for field in model:
                self.assertEqual(response.json[key][index][field], model[field], f"{index} {field}")


class TestService(TestBase):

    @unittest.mock.patch.dict(os.environ, {
        "REDIS_HOST": "most.com",
        "REDIS_PORT": "667",
        "REDIS_CHANNEL": "stuff"
    })
    @unittest.mock.patch("redis.StrictRedis", MockRedis)
    @unittest.mock.patch("os.path.exists")
    @unittest.mock.patch("pykube.KubeConfig.from_file")
    @unittest.mock.patch("pykube.KubeConfig.from_service_account")
    @unittest.mock.patch("pykube.HTTPClient", unittest.mock.MagicMock)
    def test_app(self, mock_account, mock_file, mock_exists):

        mock_exists.return_value = True
        app = service.app()

        self.assertEqual(app.redis.host, "most.com")
        self.assertEqual(app.redis.port, 667)
        self.assertEqual(app.channel, "stuff")

        mock_exists.assert_called_once_with("/opt/nandy-io/secret/config")
        mock_file.assert_called_once_with("/opt/nandy-io/secret/config")

        mock_exists.return_value = False
        app = service.app()

        mock_file.assert_called_once_with("/opt/nandy-io/secret/config")
        mock_account.assert_called_once()

    def test_require_session(self):

        mock_session = unittest.mock.MagicMock()
        self.app.mysql.session = unittest.mock.MagicMock(return_value=mock_session)

        @service.require_session
        def good():
            response = flask.make_response(json.dumps({"message": "yep"}))
            response.headers.set('Content-Type', 'application/json')
            response.status_code = 200
            return response

        self.app.add_url_rule('/good', 'good', good)

        response = self.api.get("/good")
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["message"], "yep")
        mock_session.close.assert_called_once_with()

        @service.require_session
        def bad():
            raise sqlalchemy.exc.InvalidRequestError("nope")

        self.app.add_url_rule('/bad', 'bad', bad)

        response = self.api.get("/bad")
        self.assertEqual(response.status_code, 500, response.json)
        self.assertEqual(response.json["message"], "session error")
        mock_session.rollback.assert_called_once_with()
        mock_session.close.assert_has_calls([
            unittest.mock.call(),
            unittest.mock.call()
        ])

        @service.require_session
        def ugly():
            raise Exception("whoops")

        self.app.add_url_rule('/ugly', 'ugly', ugly)

        response = self.api.get("/ugly")
        self.assertEqual(response.status_code, 500, response.json)
        self.assertEqual(response.json["message"], "whoops")
        mock_session.rollback.assert_called_once_with()
        mock_session.close.assert_has_calls([
            unittest.mock.call(),
            unittest.mock.call(),
            unittest.mock.call()
        ])

    def test_model_in(self):

        self.assertEqual(service.model_in({
            "a": 1,
            "yaml": yaml.dump({"b": 2})
        }), {
            "a": 1,
            "data": {
                "b": 2
            }
        })

    def test_model_out(self):

        area = self.sample.area(
            name="a", 
            status="b", 
            updated=3,
            data={"d": 4}
        )

        self.assertEqual(service.model_out(area), {
            "id": area.id,
            "name": "a",
            "status": "b",
            "updated": 3,
            "data": {
                "d": 4
            },
            "yaml": yaml.dump({"d": 4}, default_flow_style=False)
        })

    def test_models_out(self):

        area = self.sample.area(
            name="a", 
            status="b", 
            updated=3,
            data={"d": 4}
        )

        self.assertEqual(service.models_out([area]), [{
            "id": area.id,
            "name": "a",
            "status": "b",
            "updated": 3,
            "data": {
                "d": 4
            },
            "yaml": yaml.dump({"d": 4}, default_flow_style=False)
        }])

    @unittest.mock.patch("flask.current_app")
    def test_notify(self, mock_flask):

        mock_flask.redis = self.app.redis
        mock_flask.channel = "things"

        service.notify({"a": 1})

        self.assertEqual(self.app.redis.channel, "things")
        self.assertEqual(self.app.redis.messages, ['{"a": 1}'])


class TestHealth(TestBase):

    def test_health(self):

        self.assertEqual(self.api.get("/health").json, {"message": "OK"})


class TestPerson(TestBase):

    def test_create(self):

        response = self.api.post("/person", json={
            "person": {
                "name": "unit",
                "email": "test"
            }
        })

        self.assertStatusModel(response, 201, "person", {
            "name": "unit",
            "email": "test"
        })

        person_id = response.json["person"]["id"]

    def test_list(self):

        self.sample.person("unit")
        self.sample.person("test")

        self.assertStatusModels(self.api.get("/person"), 200, "persons", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

    def test_retrieve(self):

        person = self.sample.person("unit", "test")

        self.assertStatusModel(self.api.get(f"/person/{person.id}"), 200, "person", {
            "name": "unit",
            "email": "test"
        })

    def test_update(self):

        person = self.sample.person("unit", "test")

        self.assertStatusValue(self.api.patch(f"/person/{person.id}", json={
            "person": {
                "email": "testy"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/person/{person.id}"), 200, "person", {
            "name": "unit",
            "email": "testy"
        })

    def test_delete(self):

        person = self.sample.person("unit", "test")

        self.assertStatusValue(self.api.delete(f"/person/{person.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/person"), 200, "persons", [])


class TestArea(TestBase):

    def test_create(self):

        response = self.api.post("/area", json={
            "area": {
                "name": "unit",
                "status": "test",
                "data": {"a": 1}
            }
        })

        self.assertStatusModel(response, 201, "area", {
            "name": "unit",
            "status": "test",
            "data": {"a": 1}
        })

        area_id = response.json["area"]["id"]

    def test_list(self):

        self.sample.area("unit")
        self.sample.area("test")

        self.assertStatusModels(self.api.get("/area"), 200, "areas", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

    def test_retrieve(self):

        area = self.sample.area("unit", "test")

        self.assertStatusModel(self.api.get(f"/area/{area.id}"), 200, "area", {
            "name": "unit",
            "status": "test"
        })

    def test_update(self):

        area = self.sample.area("unit", "test")

        self.assertStatusValue(self.api.patch(f"/area/{area.id}", json={
            "area": {
                "status": "testy"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/area/{area.id}"), 200, "area", {
            "name": "unit",
            "status": "testy"
        })

    def test_delete(self):

        area = self.sample.area("unit", "test")

        self.assertStatusValue(self.api.delete(f"/area/{area.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/area"), 200, "areas", [])


class TestTemplate(TestBase):

    def test_create(self):

        response = self.api.post("/template", json={
            "template": {
                "name": "unit",
                "kind": "todo",
                "data": {"a": 1}
            }
        })

        self.assertStatusModel(response, 201, "template", {
            "name": "unit",
            "kind": "todo",
            "data": {"a": 1}
        })

    def test_list(self):

        self.sample.template("unit", "todo")
        self.sample.template("test", "act")

        self.assertStatusModels(self.api.get("/template"), 200, "templates", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

    def test_retrieve(self):

        template = self.sample.template("unit", "todo", {"a": 1})

        self.assertStatusModel(self.api.get(f"/template/{template.id}"), 200, "template", {
            "name": "unit",
            "kind": "todo",
            "data": {"a": 1},
            "yaml": "a: 1\n"
        })

    def test_update(self):

        template = self.sample.template("unit", "todo", {"a": 1})

        self.assertStatusValue(self.api.patch(f"/template/{template.id}", json={
            "template": {
                "kind": "act"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/template/{template.id}"), 200, "template", {
            "name": "unit",
            "kind": "act",
            "data": {"a": 1}
        })

    def test_delete(self):

        template = self.sample.template("unit", "todo")

        self.assertStatusValue(self.api.delete(f"/template/{template.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/template"), 200, "templates", [])

class TestRoutineAction(TestBase):

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_build(self, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit", "test")

        # basic 

        self.assertEqual(service.RoutineAction.build(**{
            "name": "hey",
            "person_id": person.id,
            "status": "started",
            "created": 1,
            "updated": 2,
            "data": {
                "by": "dict",
                "tasks": [{}]
            }
        }), {
            "name": "hey",
            "person_id": person.id,
            "status": "started",
            "created": 1,
            "updated": 2,
            "data": {
                "by": "dict",
                "language": "en-us",
                "tasks": [{
                    "id": 0
                }]
            }
        })

        # template by data, person by name

        self.assertEqual(service.RoutineAction.build(**{
            "name": "hey",
            "template": {
                "by": "data",
                "person": "unit",
                "language": "en-us",
                "tasks": [{}]
            },
            "data": {
                "language": "en-au"
            }
        }), {
            "name": "hey",
            "person_id": person.id,
            "status": "started",
            "created": 7,
            "updated": 7,
            "data": {
                "by": "data",
                "person": "unit",
                "language": "en-au",
                "tasks": [{
                    "id": 0
                }]
            }
        })

        # template by id, person by name in template

        template = self.sample.template("unit", "routine", data={"by": "id"})

        self.assertEqual(service.RoutineAction.build(**{
            "name": "hey",
            "email": "test",
            "template_id": template.id
        }), {
            "name": "hey",
            "person_id": person.id,
            "status": "started",
            "created": 7,
            "updated": 7,
            "data": {
                "by": "id",
                "language": "en-us"
            }
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey"
        })

        service.RoutineAction.notify("test", routine)

        self.assertEqual(routine.updated, 7)
        self.assertEqual(routine.data["notified"], 7)

        mock_notify.assert_called_once_with({
            "kind": "routine",
            "action": "test",
            "routine": service.model_out(routine),
            "person": service.model_out(routine.person)
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_check(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing"
        })

        service.RoutineAction.check(routine)

        mock_notify.assert_not_called()

        routine.data["tasks"] = [
            {
                "text": "do it"
            },
            {
                "text": "moo it",
                "paused": True
            }
        ]

        service.RoutineAction.check(routine)

        self.assertEqual(routine.data["tasks"][0]["start"], 7)

        mock_notify.assert_called_once_with({
            "kind": "task",
            "action": "start",
            "task": routine.data["tasks"][0],
            "routine": service.model_out(routine),
            "person": service.model_out(routine.person)
        })

        service.RoutineAction.check(routine)

        mock_notify.assert_called_once_with({
            "kind": "task",
            "action": "start",
            "task": routine.data["tasks"][0],
            "routine": service.model_out(routine),
            "person": service.model_out(routine.person)
        })

        routine.data["tasks"][0]["end"] = 0

        service.RoutineAction.check(routine)

        self.assertEqual(routine.data["tasks"][0]["start"], 7)

        mock_notify.assert_called_with({
            "kind": "task",
            "action": "pause",
            "task": routine.data["tasks"][1],
            "routine": service.model_out(routine),
            "person": service.model_out(routine.person)
        })

        routine.data["tasks"][1]["end"] = 0

        service.RoutineAction.check(routine)

        self.assertEqual(routine.status, "ended")

    @unittest.mock.patch("service.RoutineAction.notify")
    @unittest.mock.patch("service.TaskAction.notify")
    def test_start(self, mock_task_notify, mock_routine):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{"text": "do it"}]
        })

        service.RoutineAction.start(routine)

        mock_routine.assert_called_once_with("start", routine)
        mock_task_notify.assert_called_once_with("start", routine.data["tasks"][0], routine)

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_create(self, mock_flask):

        mock_flask.session = self.session

        person = self.sample.person("unit")

        routine = service.RoutineAction.create(**{
            "person_id": person.id,
            "name": "unit",
            "status": "started",
            "created": 6,
            "data": {
                "text": "hey"
            }
        })

        self.assertEqual(routine.person_id, person.id)
        self.assertEqual(routine.name, "unit")
        self.assertEqual(routine.status, "started")
        self.assertEqual(routine.created, 6)
        self.assertEqual(routine.updated, 7)
        self.assertEqual(routine.data, {
            "text": "hey",
            "language": "en-us",
            "notified": 7
        })

        item = self.session.query(mysql.Routine).get(routine.id)
        flask.request.session.commit()
        self.assertEqual(item.name, "unit")

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_next(self):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it",
                "start": 0
            }]
        })

        self.assertTrue(service.RoutineAction.next(routine))

        self.assertEqual(routine.data["tasks"][0]["end"], 7)

        self.assertFalse(service.RoutineAction.next(routine))

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_remind(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.RoutineAction.remind(routine))

        mock_notify.assert_called_once_with("remind", routine)

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_pause(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.RoutineAction.pause(routine))
        self.assertTrue(routine.data["paused"])
        mock_notify.assert_called_once_with("pause", routine)

        self.assertFalse(service.RoutineAction.pause(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unpause(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "paused": True
        })

        self.assertTrue(service.RoutineAction.unpause(routine))
        self.assertFalse(routine.data["paused"])
        mock_notify.assert_called_once_with("unpause", routine)

        self.assertFalse(service.RoutineAction.unpause(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_skip(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing"
        })

        self.assertTrue(service.RoutineAction.skip(routine))
        self.assertTrue(routine.data["skipped"])
        self.assertEqual(routine.data["end"], 7)
        self.assertEqual(routine.status, "ended")
        mock_notify.assert_called_once_with("skip", routine)

        self.assertFalse(service.RoutineAction.skip(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unskip(self, mock_notify):

        routine = self.sample.routine("unit", "hey", status="ended", data={
            "text": "hey",
            "language": "cursing",
            "skipped": True,
            "end": 0
        })

        self.assertTrue(service.RoutineAction.unskip(routine))
        self.assertFalse(routine.data["skipped"])
        self.assertNotIn("end", routine.data)
        self.assertEqual(routine.status, "started")
        mock_notify.assert_called_once_with("unskip", routine)

        self.assertFalse(service.RoutineAction.unskip(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_complete(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing"
        })

        self.assertTrue(service.RoutineAction.complete(routine))
        self.assertEqual(routine.status, "ended")
        self.assertTrue(routine.data["end"], 7)
        mock_notify.assert_called_once_with("complete", routine)

        self.assertFalse(service.RoutineAction.complete(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_uncomplete(self, mock_notify):

        routine = self.sample.routine("unit", "hey", status="ended", data={
            "text": "hey",
            "language": "cursing",
            "end": 0
        })

        self.assertTrue(service.RoutineAction.uncomplete(routine))
        self.assertNotIn("end", routine.data)
        self.assertEqual(routine.status, "started")
        mock_notify.assert_called_once_with("uncomplete", routine)

        self.assertFalse(service.RoutineAction.uncomplete(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_expire(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing"
        })

        self.assertTrue(service.RoutineAction.expire(routine))
        self.assertTrue(routine.data["expired"])
        self.assertEqual(routine.data["end"], 7)
        self.assertEqual(routine.status, "ended")
        mock_notify.assert_called_once_with("expire", routine)

        self.assertFalse(service.RoutineAction.expire(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unexpire(self, mock_notify):

        routine = self.sample.routine("unit", "hey", status="ended", data={
            "text": "hey",
            "language": "cursing",
            "expired": True,
            "end": 0
        })

        self.assertTrue(service.RoutineAction.unexpire(routine))
        self.assertFalse(routine.data["expired"])
        self.assertNotIn("end", routine.data)
        self.assertEqual(routine.status, "started")
        mock_notify.assert_called_once_with("unexpire", routine)

        self.assertFalse(service.RoutineAction.unexpire(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_action(self):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [
                {
                    "text": "do it",
                    "start": 0
                },
                {
                    "text": "moo it",
                    "start": 0
                }
            ]
        })

        # remind

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/remind"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.data["notified"], 7)

        # next

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/next"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.data["tasks"][0]["end"], 7)

        # pause

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/pause"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertTrue(item.data["paused"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/pause"), 202, "updated", False)

        # unpause

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/unpause"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertFalse(item.data["paused"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/unpause"), 202, "updated", False)

        # skip

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/skip"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertTrue(item.data["skipped"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/skip"), 202, "updated", False)

        # unskip

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/unskip"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertFalse(item.data["skipped"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/unskip"), 202, "updated", False)

        # complete

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/complete"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.status, "ended")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/complete"), 202, "updated", False)

        # uncomplete

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/uncomplete"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.status, "started")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/uncomplete"), 202, "updated", False)

        # expire

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/expire"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertTrue(item.data["expired"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/expire"), 202, "updated", False)

        # unexpire

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/unexpire"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertFalse(item.data["expired"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/unexpire"), 202, "updated", False)


class TestTaskAction(TestBase):

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "node": "plimpton",
            "tasks": [{
                "text": "you"
            }]
        })

        service.TaskAction.notify("test", routine.data["tasks"][0], routine)

        self.assertEqual(routine.updated, 7)
        self.assertEqual(routine.data["notified"], 7)
        self.assertEqual(routine.data["tasks"][0]["notified"], 7)

        mock_notify.assert_called_once_with({
            "kind": "task",
            "action": "test",
            "task": routine.data["tasks"][0],
            "routine": service.model_out(routine),
            "person": service.model_out(routine.person)
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    def test_remind(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it"
            }]
        })

        self.assertTrue(service.TaskAction.remind(routine.data["tasks"][0], routine))
        mock_notify.assert_called_once_with("remind", routine.data["tasks"][0], routine)

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    def test_pause(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it"
            }]
        })

        self.assertTrue(service.TaskAction.pause(routine.data["tasks"][0], routine))
        self.assertTrue(routine.data["tasks"][0]["paused"])
        mock_notify.assert_called_once_with("pause", routine.data["tasks"][0], routine)

        self.assertFalse(service.TaskAction.pause(routine.data["tasks"][0], routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    def test_unpause(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it",
                "paused": True
            }]
        })

        self.assertTrue(service.TaskAction.unpause(routine.data["tasks"][0], routine))
        self.assertFalse(routine.data["tasks"][0]["paused"])
        mock_notify.assert_called_once_with("unpause", routine.data["tasks"][0], routine)

        self.assertFalse(service.TaskAction.unpause(routine.data["tasks"][0], routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_skip(self, mock_routine_notify, mock_task_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it"
            }]
        })

        self.assertTrue(service.TaskAction.skip(routine.data["tasks"][0], routine))
        self.assertTrue(routine.data["tasks"][0]["skipped"])
        self.assertEqual(routine.data["tasks"][0]["start"], 7)
        self.assertEqual(routine.data["tasks"][0]["end"], 7)
        self.assertEqual(routine.status, "ended")
        mock_task_notify.assert_called_once_with("skip", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("complete", routine)

        self.assertFalse(service.TaskAction.skip(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unskip(self, mock_routine_notify, mock_task_notify):

        routine = self.sample.routine("unit", "hey", status="ended", data={
            "text": "hey",
            "language": "cursing",
            "end": 0,
            "tasks": [{
                "text": "do it",
                "skipped": True,
                "end": 0
            }]
        })

        self.assertTrue(service.TaskAction.unskip(routine.data["tasks"][0], routine))
        self.assertFalse(routine.data["tasks"][0]["skipped"])
        self.assertNotIn("end", routine.data["tasks"][0])
        self.assertEqual(routine.status, "started")
        mock_task_notify.assert_called_once_with("unskip", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("uncomplete", routine)

        self.assertFalse(service.TaskAction.unskip(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_complete(self, mock_routine_notify, mock_task_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it"
            }]
        })

        self.assertTrue(service.TaskAction.complete(routine.data["tasks"][0], routine))
        self.assertTrue(routine.data["tasks"][0]["end"], 7)
        self.assertEqual(routine.status, "ended")
        mock_task_notify.assert_called_once_with("complete", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("complete", routine)

        self.assertFalse(service.TaskAction.complete(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()
    
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_uncomplete(self, mock_routine_notify, mock_task_notify):

        routine = self.sample.routine("unit", "hey", status="ended", data={
            "text": "hey",
            "language": "cursing",
            "end": 0,
            "tasks": [{
                "text": "do it",
                "end": 0
            }]
        })

        self.assertTrue(service.TaskAction.uncomplete(routine.data["tasks"][0], routine))
        self.assertNotIn("end", routine.data["tasks"][0])
        self.assertEqual(routine.status, "started")
        mock_task_notify.assert_called_once_with("uncomplete", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("uncomplete", routine)

        self.assertFalse(service.TaskAction.uncomplete(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_action(self):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [
                {
                    "text": "do it"
                }
            ]
        })

        # remind

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/remind"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.data["tasks"][0]["notified"], 7)

        # pause

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/pause"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertTrue(item.data["tasks"][0]["paused"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/pause"), 202, "updated", False)

        # unpause

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/unpause"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertFalse(item.data["tasks"][0]["paused"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/unpause"), 202, "updated", False)

        # skip

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/skip"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertTrue(item.data["tasks"][0]["skipped"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/skip"), 202, "updated", False)

        # unskip

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/unskip"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertFalse(item.data["tasks"][0]["skipped"])
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/unskip"), 202, "updated", False)

        # complete

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/complete"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.status, "ended")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/complete"), 202, "updated", False)

        # uncomplete

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/uncomplete"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.status, "started")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/uncomplete"), 202, "updated", False)


class TestRoutine(TestBase):

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_create(self):

        person = self.sample.person("unit")

        response = self.api.post("/routine", json={
            "routine": {
                "person_id": person.id,
                "name": "unit",
                "status": "started",
                "created": 6,
                "data": {
                    "text": "hey"
                }
            }
        })

        self.assertStatusModel(response, 201, "routine", {
            "person_id": person.id,
            "name": "unit",
            "status": "started",
            "created": 6,
            "updated": 7,
            "data": {
                "text": "hey",
                "language": "en-us",
                "notified": 7
            }
        })

    def test_list(self):

        self.sample.routine("unit", "test", created=7)
        self.sample.routine("test", "unit", created=6)

        self.assertStatusModels(self.api.get("/routine"), 200, "routines", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

    def test_retrieve(self):

        routine = self.sample.routine("test", "unit")

        self.assertStatusModel(self.api.get(f"/routine/{routine.id}"), 200, "routine", {
            "person_id": routine.person_id,
            "name": "unit",
            "status": "started",
            "created": 7,
            "data": {
                "text": "routine it",
                "language": "en-us"
            },
            "yaml": "language: en-us\ntext: routine it\n"
        })

    def test_update(self):

        routine = self.sample.routine("test", "unit")

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}", json={
            "routine": {
                "status": "ended"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/routine/{routine.id}"), 200, "routine", {
            "status": "ended"
        })

    def test_delete(self):

        routine = self.sample.routine("test", "unit")

        self.assertStatusValue(self.api.delete(f"/routine/{routine.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/routine"), 200, "routines", [])


class TestToDo(TestBase):

    def test_ToDo(self):

        # Person

        person_id = self.api.post("/person", json={
            "person": {
                "name": "unit",
                "email": "test"
            }
        }).json["person"]["id"]

        # Create

        response = self.api.post("/todo", json={
            "todo": {
                "person_id": person_id,
                "name": "unit",
                "status": "needed",
                "created": 6,
                "data": {"a": 1}
            }
        })

        self.assertStatusModel(response, 201, "todo", {
            "person_id": person_id,
            "name": "unit",
            "status": "needed",
            "created": 6,
            "data": {"a": 1}
        })

        todo_id = response.json["todo"]["id"]

        # List

        self.sample.todo("test", "test")

        self.assertStatusModels(self.api.get("/todo"), 200, "todos", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

        # Retrieve

        self.assertStatusModel(self.api.get(f"/todo/{todo_id}"), 200, "todo", {
            "person_id": person_id,
            "name": "unit",
            "status": "needed",
            "created": 6,
            "data": {"a": 1}
        })

        # Update

        self.assertStatusValue(self.api.patch(f"/todo/{todo_id}", json={
            "todo": {
                "status": "completed"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/todo/{todo_id}"), 200, "todo", {
            "name": "unit",
            "status": "completed"
        })

        # Delete

        self.assertStatusValue(self.api.delete(f"/todo/{todo_id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/todo"), 200, "todos", [
            {
                "name": "test"
            }
        ])


class TestAct(TestBase):

    def test_Act(self):

        # Person

        person_id = self.api.post("/person", json={
            "person": {
                "name": "unit",
                "email": "test"
            }
        }).json["person"]["id"]

        # Create

        response = self.api.post("/act", json={
            "act": {
                "person_id": person_id,
                "name": "unit",
                "value": "negative",
                "created": 6,
                "data": {"a": 1}
            }
        })

        self.assertStatusModel(response, 201, "act", {
            "person_id": person_id,
            "name": "unit",
            "value": "negative",
            "created": 6,
            "data": {"a": 1}
        })

        act_id = response.json["act"]["id"]

        # List

        self.sample.act("test", "test")

        self.assertStatusModels(self.api.get("/act"), 200, "acts", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

        # Retrieve

        self.assertStatusModel(self.api.get(f"/act/{act_id}"), 200, "act", {
            "person_id": person_id,
            "name": "unit",
            "value": "negative",
            "created": 6,
            "data": {"a": 1}
        })

        # Update

        self.assertStatusValue(self.api.patch(f"/act/{act_id}", json={
            "act": {
                "value": "positive"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/act/{act_id}"), 200, "act", {
            "name": "unit",
            "value": "positive"
        })

        # Delete

        self.assertStatusValue(self.api.delete(f"/act/{act_id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/act"), 200, "acts", [
            {
                "name": "test"
            }
        ])
