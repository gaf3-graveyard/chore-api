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
    @unittest.mock.patch("os.path.exists", unittest.mock.MagicMock(return_value=True))
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
    @unittest.mock.patch("pykube.KubeConfig.from_url")
    @unittest.mock.patch("pykube.HTTPClient", unittest.mock.MagicMock)
    def test_app(self, mock_url, mock_account, mock_file, mock_exists):

        mock_exists.return_value = True
        app = service.app()

        self.assertEqual(app.redis.host, "most.com")
        self.assertEqual(app.redis.port, 667)
        self.assertEqual(app.channel, "stuff")

        mock_exists.assert_called_once_with("/var/run/secrets/kubernetes.io/serviceaccount/token")
        mock_account.assert_called_once()

        mock_exists.return_value = False
        app = service.app()

        mock_url.assert_called_once_with("http://host.docker.internal:7580")

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
            "unit",
            name="a", 
            status="positive", 
            created=2,
            updated=3,
            data={"d": 4}
        )

        self.assertEqual(service.model_out(area), {
            "id": area.id,
            "person_id": area.person.id,
            "name": "a",
            "status": "positive",
            "created": 2,
            "updated": 3,
            "data": {
                "d": 4
            },
            "yaml": yaml.dump({"d": 4}, default_flow_style=False)
        })

    def test_models_out(self):

        area = self.sample.area(
            "unit",
            name="a", 
            status="positive", 
            created=2,
            updated=3,
            data={"d": 4}
        )

        self.assertEqual(service.models_out([area]), [{
            "id": area.id,
            "person_id": area.person.id,
            "name": "a",
            "status": "positive",
            "created": 2,
            "updated": 3,
            "data": {
                "d": 4
            },
            "yaml": yaml.dump({"d": 4}, default_flow_style=False)
        }])

    @unittest.mock.patch("flask.current_app")
    def test_notify(self, mock_request):

        mock_request.redis = self.app.redis
        mock_request.channel = "things"

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
                "name": "unit"
            }
        })

        self.assertStatusModel(response, 201, "person", {
            "name": "unit"
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

        person = self.sample.person("unit")

        self.assertStatusModel(self.api.get(f"/person/{person.id}"), 200, "person", {
            "name": "unit"
        })

    def test_update(self):

        person = self.sample.person("unit")

        self.assertStatusValue(self.api.patch(f"/person/{person.id}", json={
            "person": {
                "name": "unity"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/person/{person.id}"), 200, "person", {
            "name": "unity"
        })

    def test_delete(self):

        person = self.sample.person("unit")

        self.assertStatusValue(self.api.delete(f"/person/{person.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/person"), 200, "persons", [])


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


class TestArea(TestBase):

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_build(self, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        # basic 

        self.assertEqual(service.AreaValue.build(**{
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "positive",
                "created": 1,
                "updated": 2
            }
        }), {
            "person_id": person.id,
            "name": "hey",
            "status": "positive",
            "created": 1,
            "updated": 2,
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "positive",
                "created": 1,
                "updated": 2
            }
        })

        # template by data, person by name

        self.assertEqual(service.AreaValue.build(**{
            "template": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        }), {
            "name": "hey",
            "person_id": person.id,
            "data": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        })

        # template by id, person by name in template

        template = self.sample.template("unit", "routine", data={
            "by": "template_id",
            "status": "negative"
        })

        self.assertEqual(service.AreaValue.build(**{
            "name": "hey",
            "template_id": template.id
        }), {
            "name": "hey",
            "status": "negative",
            "data": {
                "by": "template_id",
                "status": "negative"
            }
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        model = self.sample.area("unit", "test")

        service.AreaValue.notify("test", model)

        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data["notified"], 7)

        mock_notify.assert_called_once_with({
            "kind": "area",
            "action": "test",
            "area": service.model_out(model),
            "person": service.model_out(model.person)
        })

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_create(self, mock_notify, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        model = service.AreaValue.create(**{
            "person_id": person.id,
            "name": "unit",
            "created": 6,
            "data": {
                "text": "hey"
            }
        })

        self.assertEqual(model.person_id, person.id)
        self.assertEqual(model.name, "unit")
        self.assertEqual(model.status, "positive")
        self.assertEqual(model.created, 6)
        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data, {
            "text": "hey",
            "notified": 7
        })

        item = self.session.query(mysql.Area).get(model.id)
        flask.request.session.commit()
        self.assertEqual(item.name, "unit")

        mock_notify.assert_called_once_with({
            "kind": "area",
            "action": "create",
            "area": service.model_out(model),
            "person": service.model_out(model.person)
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_post(self):

        person = self.sample.person("unit")

        response = self.api.post("/area", json={
            "area": {
                "person_id": person.id,
                "name": "unit",
                "status": "negative",
                "data": {
                    "a": 1
                }
            }
        })

        self.assertStatusModel(response, 201, "area", {
            "person_id": person.id,
            "name": "unit",
            "status": "negative",
            "data": {
                "a": 1,
                "notified": 7
            }
        })

        area_id = response.json["area"]["id"]

    def test_list(self):

        self.sample.area("unit", "test")
        self.sample.area("test", "unit")

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
            "name": "test"
        })

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseStatus.notify")
    def test_wrong(self, mock_notify, mock_request):

        mock_request.session = self.session

        model = self.sample.area("unit", "hey", data={
            "todo": {
                "name": "Unit",
                "text": "test"
            }
        })

        self.assertTrue(service.AreaValue.wrong(model))
        self.assertEqual(model.status, "negative")
        item = self.session.query(mysql.ToDo).all()[0]
        self.assertEqual(item.person.id, model.person.id)
        self.assertEqual(item.name, "Unit")
        self.assertEqual(item.data["text"], "test")
        self.assertEqual(item.data["area"], model.id)
        mock_notify.assert_has_calls([
            unittest.mock.call("wrong", model),
            unittest.mock.call("create", item)
        ])

        self.assertFalse(service.AreaValue.wrong(model))
        self.assertEqual(mock_notify.call_count, 2)

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseStatus.notify")
    def test_right(self, mock_notify):

        model = self.sample.area("unit", "hey", status="negative")

        self.assertTrue(service.AreaValue.right(model))
        self.assertEqual(model.status, "positive")
        mock_notify.assert_called_once_with("right", model)

        self.assertFalse(service.AreaValue.right(model))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_action(self):

        model = self.sample.area("unit", "hey")

        # wrong

        self.assertStatusValue(self.api.patch(f"/area/{model.id}/wrong"), 202, "updated", True)
        item = self.session.query(mysql.Area).get(model.id)
        self.session.commit()
        self.assertEqual(item.status, "negative")
        self.assertStatusValue(self.api.patch(f"/area/{model.id}/wrong"), 202, "updated", False)

        # right

        self.assertStatusValue(self.api.patch(f"/area/{model.id}/right"), 202, "updated", True)
        item = self.session.query(mysql.Area).get(model.id)
        self.session.commit()
        self.assertEqual(item.status, "positive")
        self.assertStatusValue(self.api.patch(f"/area/{model.id}/right"), 202, "updated", False)

    def test_update(self):

        area = self.sample.area("unit", "test")

        self.assertStatusValue(self.api.patch(f"/area/{area.id}", json={
            "area": {
                "status": "negative"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/area/{area.id}"), 200, "area", {
            "name": "test",
            "status": "negative"
        })

    def test_delete(self):

        area = self.sample.area("unit", "test")

        self.assertStatusValue(self.api.delete(f"/area/{area.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/area"), 200, "areas", [])


class TestAct(TestBase):

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_build(self, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        # basic 

        self.assertEqual(service.ActValue.build(**{
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "positive",
                "created": 1,
                "updated": 2
            }
        }), {
            "person_id": person.id,
            "name": "hey",
            "status": "positive",
            "created": 1,
            "updated": 2,
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "positive",
                "created": 1,
                "updated": 2
            }
        })

        # template by data, person by name

        self.assertEqual(service.ActValue.build(**{
            "template": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        }), {
            "name": "hey",
            "person_id": person.id,
            "data": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        })

        # template by id, person by name in template

        template = self.sample.template("unit", "routine", data={
            "by": "template_id",
            "status": "negative"
        })

        self.assertEqual(service.ActValue.build(**{
            "name": "hey",
            "template_id": template.id
        }), {
            "name": "hey",
            "status": "negative",
            "data": {
                "by": "template_id",
                "status": "negative"
            }
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        model = self.sample.act("unit", "test")

        service.ActValue.notify("test", model)

        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data["notified"], 7)

        mock_notify.assert_called_once_with({
            "kind": "act",
            "action": "test",
            "act": service.model_out(model),
            "person": service.model_out(model.person)
        })

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_create(self, mock_notify, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        model = service.ActValue.create(**{
            "person_id": person.id,
            "name": "unit",
            "status": "negative",
            "created": 6,
            "data": {
                "text": "hey",
                "todo": {
                    "name": "Unit",
                    "text": "test"
                }
            }
        })

        self.assertEqual(model.person_id, person.id)
        self.assertEqual(model.name, "unit")
        self.assertEqual(model.status, "negative")
        self.assertEqual(model.created, 6)
        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data, {
            "text": "hey",
            "notified": 7,
            "todo": {
                "name": "Unit",
                "text": "test"
            }
        })

        todo = self.session.query(mysql.ToDo).filter_by(name="Unit").all()[0]
        flask.request.session.commit()
        self.assertEqual(todo.data["text"], "test")

        item = self.session.query(mysql.Act).get(model.id)
        flask.request.session.commit()
        self.assertEqual(item.name, "unit")

        mock_notify.assert_has_calls([
            unittest.mock.call({
                "kind": "act",
                "action": "create",
                "act": service.model_out(model),
                "person": service.model_out(model.person)
            }),
            unittest.mock.call({
                "kind": "todo",
                "action": "create",
                "todo": service.model_out(todo),
                "person": service.model_out(todo.person)
            })
        ])

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_post(self):

        person = self.sample.person("unit")

        response = self.api.post("/act", json={
            "act": {
                "person_id": person.id,
                "name": "unit",
                "status": "negative",
                "data": {
                    "a": 1
                }
            }
        })

        self.assertStatusModel(response, 201, "act", {
            "person_id": person.id,
            "name": "unit",
            "status": "negative",
            "data": {
                "a": 1,
                "notified": 7
            }
        })

        act_id = response.json["act"]["id"]

    def test_list(self):

        self.sample.act("unit", "test")
        self.sample.act("test", "unit")

        self.assertStatusModels(self.api.get("/act"), 200, "acts", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

    def test_retrieve(self):

        act = self.sample.act("unit", "test")

        self.assertStatusModel(self.api.get(f"/act/{act.id}"), 200, "act", {
            "name": "test"
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseStatus.notify")
    def test_wrong(self, mock_notify):

        model = self.sample.act("unit", "hey")

        self.assertTrue(service.ActValue.wrong(model))
        self.assertEqual(model.status, "negative")
        mock_notify.assert_called_once_with("wrong", model)

        self.assertFalse(service.ActValue.wrong(model))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseStatus.notify")
    def test_right(self, mock_notify):

        model = self.sample.act("unit", "hey", status="negative")

        self.assertTrue(service.ActValue.right(model))
        self.assertEqual(model.status, "positive")
        mock_notify.assert_called_once_with("right", model)

        self.assertFalse(service.ActValue.right(model))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_action(self):

        model = self.sample.act("unit", "hey")

        # wrong

        self.assertStatusValue(self.api.patch(f"/act/{model.id}/wrong"), 202, "updated", True)
        item = self.session.query(mysql.Act).get(model.id)
        self.session.commit()
        self.assertEqual(item.status, "negative")
        self.assertStatusValue(self.api.patch(f"/act/{model.id}/wrong"), 202, "updated", False)

        # right

        self.assertStatusValue(self.api.patch(f"/act/{model.id}/right"), 202, "updated", True)
        item = self.session.query(mysql.Act).get(model.id)
        self.session.commit()
        self.assertEqual(item.status, "positive")
        self.assertStatusValue(self.api.patch(f"/act/{model.id}/right"), 202, "updated", False)

    def test_update(self):

        act = self.sample.act("unit", "test")

        self.assertStatusValue(self.api.patch(f"/act/{act.id}", json={
            "act": {
                "status": "negative"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/act/{act.id}"), 200, "act", {
            "name": "test",
            "status": "negative"
        })

    def test_delete(self):

        act = self.sample.act("unit", "test")

        self.assertStatusValue(self.api.delete(f"/act/{act.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/act"), 200, "acts", [])


class TestToDo(TestBase):

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_build(self, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        # basic 

        self.assertEqual(service.ToDoAction.build(**{
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "opened",
                "created": 1,
                "updated": 2
            }
        }), {
            "person_id": person.id,
            "name": "hey",
            "status": "opened",
            "created": 1,
            "updated": 2,
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "opened",
                "created": 1,
                "updated": 2
            }
        })

        # template by data, person by name

        self.assertEqual(service.ToDoAction.build(**{
            "template": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        }), {
            "name": "hey",
            "person_id": person.id,
            "data": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        })

        # template by id, person by name in template

        template = self.sample.template("unit", "todo", data={
            "by": "template_id",
            "status": "closed"
        })

        self.assertEqual(service.ToDoAction.build(**{
            "name": "hey",
            "template_id": template.id
        }), {
            "name": "hey",
            "status": "closed",
            "data": {
                "by": "template_id",
                "status": "closed"
            }
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        model = self.sample.todo("unit", "test")

        service.ToDoAction.notify("test", model)

        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data["notified"], 7)

        mock_notify.assert_called_once_with({
            "kind": "todo",
            "action": "test",
            "todo": service.model_out(model),
            "person": service.model_out(model.person)
        })

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_create(self, mock_notify, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        model = service.ToDoAction.create(**{
            "person_id": person.id,
            "name": "unit",
            "created": 6,
            "data": {
                "text": "hey"
            }
        })

        self.assertEqual(model.person_id, person.id)
        self.assertEqual(model.name, "unit")
        self.assertEqual(model.status, "opened")
        self.assertEqual(model.created, 6)
        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data, {
            "text": "hey",
            "notified": 7
        })

        item = self.session.query(mysql.ToDo).get(model.id)
        flask.request.session.commit()
        self.assertEqual(item.name, "unit")

        mock_notify.assert_called_once_with({
            "kind": "todo",
            "action": "create",
            "todo": service.model_out(model),
            "person": service.model_out(model.person)
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_post(self):

        person = self.sample.person("unit")

        response = self.api.post("/todo", json={
            "todo": {
                "person_id": person.id,
                "name": "unit",
                "status": "closed",
                "data": {
                    "a": 1
                }
            }
        })

        self.assertStatusModel(response, 201, "todo", {
            "person_id": person.id,
            "name": "unit",
            "status": "closed",
            "data": {
                "a": 1,
                "notified": 7
            }
        })

        todo_id = response.json["todo"]["id"]

    def test_list(self):

        self.sample.todo("unit", "test")
        self.sample.todo("test", "unit")

        self.assertStatusModels(self.api.get("/todo"), 200, "todos", [
            {
                "name": "test"
            },
            {
                "name": "unit"
            }
        ])

    def test_retrieve(self):

        todo = self.sample.todo("unit", "test")

        self.assertStatusModel(self.api.get(f"/todo/{todo.id}"), 200, "todo", {
            "name": "test"
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_remind(self, mock_notify):

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.ToDoAction.remind(todo))

        mock_notify.assert_called_once_with("remind", todo)

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_pause(self, mock_notify):

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.ToDoAction.pause(todo))
        self.assertTrue(todo.data["paused"])
        mock_notify.assert_called_once_with("pause", todo)

        self.assertFalse(service.ToDoAction.pause(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_unpause(self, mock_notify):

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey",
            "paused": True
        })

        self.assertTrue(service.ToDoAction.unpause(todo))
        self.assertFalse(todo.data["paused"])
        mock_notify.assert_called_once_with("unpause", todo)

        self.assertFalse(service.ToDoAction.unpause(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_skip(self, mock_notify):

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.ToDoAction.skip(todo))
        self.assertTrue(todo.data["skipped"])
        self.assertEqual(todo.data["end"], 7)
        self.assertEqual(todo.status, "closed")
        mock_notify.assert_called_once_with("skip", todo)

        self.assertFalse(service.ToDoAction.skip(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_unskip(self, mock_notify):

        todo = self.sample.todo("unit", "hey", status="closed", data={
            "text": "hey",
            "skipped": True,
            "end": 0
        })

        self.assertTrue(service.ToDoAction.unskip(todo))
        self.assertFalse(todo.data["skipped"])
        self.assertNotIn("end", todo.data)
        self.assertEqual(todo.status, "opened")
        mock_notify.assert_called_once_with("unskip", todo)

        self.assertFalse(service.ToDoAction.unskip(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock())
    def test_complete(self, mock_notify, mock_request):

        mock_request.session = self.session

        area = self.sample.area("unit", "test", status="negative")

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey",
            "area": area.id,
            "act": {
                "name": "Unit",
                "text": "test"
            }
        })

        self.assertTrue(service.ToDoAction.complete(todo))
        self.assertEqual(todo.status, "closed")
        self.assertTrue(todo.data["end"], 7)

        item = self.session.query(mysql.Area).get(area.id)
        self.assertEqual(item.status, "positive")
        mock_notify.assert_called_once_with("complete", todo)

        act = self.session.query(mysql.Act).filter_by(name="Unit").all()[0]
        self.assertEqual(act.person.id, todo.person.id)
        self.assertEqual(act.status, "positive")
        self.assertEqual(act.data["text"], "test")

        self.assertFalse(service.ToDoAction.complete(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_uncomplete(self, mock_notify):

        todo = self.sample.todo("unit", "hey", status="closed", data={
            "text": "hey",
            "end": 0
        })

        self.assertTrue(service.ToDoAction.uncomplete(todo))
        self.assertNotIn("end", todo.data)
        self.assertEqual(todo.status, "opened")
        mock_notify.assert_called_once_with("uncomplete", todo)

        self.assertFalse(service.ToDoAction.uncomplete(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_expire(self, mock_notify):

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.ToDoAction.expire(todo))
        self.assertTrue(todo.data["expired"])
        self.assertEqual(todo.data["end"], 7)
        self.assertEqual(todo.status, "closed")
        mock_notify.assert_called_once_with("expire", todo)

        self.assertFalse(service.ToDoAction.expire(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.BaseAction.notify")
    def test_unexpire(self, mock_notify):

        todo = self.sample.todo("unit", "hey", status="closed", data={
            "text": "hey",
            "expired": True,
            "end": 0
        })

        self.assertTrue(service.ToDoAction.unexpire(todo))
        self.assertFalse(todo.data["expired"])
        self.assertNotIn("end", todo.data)
        self.assertEqual(todo.status, "opened")
        mock_notify.assert_called_once_with("unexpire", todo)

        self.assertFalse(service.ToDoAction.unexpire(todo))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_action(self):

        todo = self.sample.todo("unit", "hey", data={
            "text": "hey"
        })

        # remind

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/remind"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertEqual(item.data["notified"], 7)

        # pause

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/pause"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertTrue(item.data["paused"])
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/pause"), 202, "updated", False)

        # unpause

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/unpause"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertFalse(item.data["paused"])
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/unpause"), 202, "updated", False)

        # skip

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/skip"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertTrue(item.data["skipped"])
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/skip"), 202, "updated", False)

        # unskip

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/unskip"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertFalse(item.data["skipped"])
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/unskip"), 202, "updated", False)

        # complete

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/complete"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertEqual(item.status, "closed")
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/complete"), 202, "updated", False)

        # uncomplete

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/uncomplete"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertEqual(item.status, "opened")
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/uncomplete"), 202, "updated", False)

        # expire

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/expire"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertTrue(item.data["expired"])
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/expire"), 202, "updated", False)

        # unexpire

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/unexpire"), 202, "updated", True)
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.session.commit()
        self.assertFalse(item.data["expired"])
        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}/unexpire"), 202, "updated", False)

    def test_update(self):

        todo = self.sample.todo("unit", "test")

        self.assertStatusValue(self.api.patch(f"/todo/{todo.id}", json={
            "todo": {
                "status": "closed"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/todo/{todo.id}"), 200, "todo", {
            "name": "test",
            "status": "closed"
        })

    def test_delete(self):

        todo = self.sample.todo("unit", "test")

        self.assertStatusValue(self.api.delete(f"/todo/{todo.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/todo"), 200, "areas", [])


class TestRoutine(TestBase):

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    def test_build(self, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        todo = self.sample.todo("unit")
        self.sample.todo("unit", status="closed")
        self.sample.todo("test")

        # explicit 

        self.assertEqual(service.RoutineAction.build(**{
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "opened",
                "created": 1,
                "updated": 2,
                "todos": True,
                "tasks": [{}]
            }
        }), {
            "person_id": person.id,
            "name": "hey",
            "status": "opened",
            "created": 1,
            "updated": 2,
            "data": {
                "by": "data",
                "person_id": person.id,
                "name": "hey",
                "status": "opened",
                "created": 1,
                "updated": 2,
                "todos": True,
                "tasks": [
                    {
                        "id": 0,
                        "text": "todo it",
                        "todo": todo.id

                    },
                    {
                        "id": 1
                    }
                ]
            }
        })

        # template by data, person by name

        self.assertEqual(service.RoutineAction.build(**{
            "template": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        }), {
            "name": "hey",
            "person_id": person.id,
            "data": {
                "by": "template",
                "name": "hey",
                "person": "unit"
            }
        })

        # template by id, person by name in template

        template = self.sample.template("unit", "routine", data={
            "by": "template_id",
            "status": "closed"
        })

        self.assertEqual(service.RoutineAction.build(**{
            "name": "hey",
            "template_id": template.id
        }), {
            "name": "hey",
            "status": "closed",
            "data": {
                "by": "template_id",
                "status": "closed"
            }
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        model = self.sample.routine("unit", "test")

        service.RoutineAction.notify("test", model)

        self.assertEqual(model.updated, 7)
        self.assertEqual(model.data["notified"], 7)

        mock_notify.assert_called_once_with({
            "kind": "routine",
            "action": "test",
            "routine": service.model_out(model),
            "person": service.model_out(model.person)
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_check(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey"
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

        self.assertEqual(routine.status, "closed")

    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_create(self, mock_request):

        mock_request.session = self.session

        person = self.sample.person("unit")

        routine = service.RoutineAction.create(**{
            "person_id": person.id,
            "name": "unit",
            "status": "opened",
            "created": 6,
            "data": {
                "text": "hey",
                "tasks": [{}]
            }
        })

        self.assertEqual(routine.person_id, person.id)
        self.assertEqual(routine.name, "unit")
        self.assertEqual(routine.status, "opened")
        self.assertEqual(routine.created, 6)
        self.assertEqual(routine.updated, 7)
        self.assertEqual(routine.data, {
            "text": "hey",
            "start": 7,
            "notified": 7,
            "notified": 7,
                "tasks": [{
                    "id": 0,
                    "start": 7,
                    "notified": 7
                }]
        })

        item = self.session.query(mysql.Routine).get(routine.id)
        flask.request.session.commit()
        self.assertEqual(item.name, "unit")

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_post(self):

        person = self.sample.person("unit")

        response = self.api.post("/routine", json={
            "routine": {
                "person_id": person.id,
                "name": "unit",
                "status": "opened",
                "created": 6,
                "data": {
                    "text": "hey"
                }
            }
        })

        self.assertStatusModel(response, 201, "routine", {
            "person_id": person.id,
            "name": "unit",
            "status": "opened",
            "created": 6,
            "updated": 7,
            "data": {
                "text": "hey",
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
            "status": "opened",
            "created": 7,
            "data": {
                "text": "routine it"
            },
            "yaml": "text: routine it\n"
        })

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_next(self):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
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
            "text": "hey"
        })

        self.assertTrue(service.RoutineAction.skip(routine))
        self.assertTrue(routine.data["skipped"])
        self.assertEqual(routine.data["end"], 7)
        self.assertEqual(routine.status, "closed")
        mock_notify.assert_called_once_with("skip", routine)

        self.assertFalse(service.RoutineAction.skip(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unskip(self, mock_notify):

        routine = self.sample.routine("unit", "hey", status="closed", data={
            "text": "hey",
            "skipped": True,
            "end": 0
        })

        self.assertTrue(service.RoutineAction.unskip(routine))
        self.assertFalse(routine.data["skipped"])
        self.assertNotIn("end", routine.data)
        self.assertEqual(routine.status, "opened")
        mock_notify.assert_called_once_with("unskip", routine)

        self.assertFalse(service.RoutineAction.unskip(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_complete(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.RoutineAction.complete(routine))
        self.assertEqual(routine.status, "closed")
        self.assertTrue(routine.data["end"], 7)
        mock_notify.assert_called_once_with("complete", routine)

        self.assertFalse(service.RoutineAction.complete(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_uncomplete(self, mock_notify):

        routine = self.sample.routine("unit", "hey", status="closed", data={
            "text": "hey",
            "end": 0
        })

        self.assertTrue(service.RoutineAction.uncomplete(routine))
        self.assertNotIn("end", routine.data)
        self.assertEqual(routine.status, "opened")
        mock_notify.assert_called_once_with("uncomplete", routine)

        self.assertFalse(service.RoutineAction.uncomplete(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_expire(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey"
        })

        self.assertTrue(service.RoutineAction.expire(routine))
        self.assertTrue(routine.data["expired"])
        self.assertEqual(routine.data["end"], 7)
        self.assertEqual(routine.status, "closed")
        mock_notify.assert_called_once_with("expire", routine)

        self.assertFalse(service.RoutineAction.expire(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unexpire(self, mock_notify):

        routine = self.sample.routine("unit", "hey", status="closed", data={
            "text": "hey",
            "expired": True,
            "end": 0
        })

        self.assertTrue(service.RoutineAction.unexpire(routine))
        self.assertFalse(routine.data["expired"])
        self.assertNotIn("end", routine.data)
        self.assertEqual(routine.status, "opened")
        mock_notify.assert_called_once_with("unexpire", routine)

        self.assertFalse(service.RoutineAction.unexpire(routine))
        mock_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify", unittest.mock.MagicMock)
    def test_action(self):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
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
        self.assertEqual(item.status, "closed")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/complete"), 202, "updated", False)

        # uncomplete

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/uncomplete"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.status, "opened")
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

    def test_update(self):

        routine = self.sample.routine("test", "unit")

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}", json={
            "routine": {
                "status": "closed"
            }
        }), 202, "updated", 1)

        self.assertStatusModel(self.api.get(f"/routine/{routine.id}"), 200, "routine", {
            "status": "closed"
        })

    def test_delete(self):

        routine = self.sample.routine("test", "unit")

        self.assertStatusValue(self.api.delete(f"/routine/{routine.id}"), 202, "deleted", 1)

        self.assertStatusModels(self.api.get("/routine"), 200, "routines", [])


class TestTask(TestBase):

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.notify")
    def test_notify(self, mock_notify):

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
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
        self.assertEqual(routine.status, "closed")
        mock_task_notify.assert_called_once_with("skip", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("complete", routine)

        self.assertFalse(service.TaskAction.skip(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()

    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    def test_unskip(self, mock_routine_notify, mock_task_notify):

        routine = self.sample.routine("unit", "hey", status="closed", data={
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
        self.assertEqual(routine.status, "opened")
        mock_task_notify.assert_called_once_with("unskip", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("uncomplete", routine)

        self.assertFalse(service.TaskAction.unskip(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()


    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    @unittest.mock.patch("service.ToDoAction.notify", unittest.mock.MagicMock())
    def test_complete(self, mock_routine_notify, mock_task_notify, mock_request):

        mock_request.session = self.session

        todo = self.sample.todo("unit")

        routine = self.sample.routine("unit", "hey", data={
            "text": "hey",
            "language": "cursing",
            "tasks": [{
                "text": "do it",
                "todo": todo.id
            }]
        })

        self.assertTrue(service.TaskAction.complete(routine.data["tasks"][0], routine))
        self.assertTrue(routine.data["tasks"][0]["end"], 7)
        self.assertEqual(routine.status, "closed")
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.assertEqual(item.status, "closed")
        mock_task_notify.assert_called_once_with("complete", routine.data["tasks"][0], routine)
        mock_routine_notify.assert_called_once_with("complete", routine)

        self.assertFalse(service.TaskAction.complete(routine.data["tasks"][0], routine))
        mock_task_notify.assert_called_once()
        mock_routine_notify.assert_called_once()
    
    @unittest.mock.patch("flask.request")
    @unittest.mock.patch("service.time.time", unittest.mock.MagicMock(return_value=7))
    @unittest.mock.patch("service.TaskAction.notify")
    @unittest.mock.patch("service.RoutineAction.notify")
    @unittest.mock.patch("service.ToDoAction.notify", unittest.mock.MagicMock())
    def test_uncomplete(self, mock_routine_notify, mock_task_notify, mock_request):

        mock_request.session = self.session

        todo = self.sample.todo("unit", status="closed", data={"end": 0})

        routine = self.sample.routine("unit", "hey", status="closed", data={
            "text": "hey",
            "language": "cursing",
            "end": 0,
            "tasks": [{
                "text": "do it",
                "end": 0,
                "todo": todo.id
            }]
        })

        self.assertTrue(service.TaskAction.uncomplete(routine.data["tasks"][0], routine))
        self.assertNotIn("end", routine.data["tasks"][0])
        self.assertEqual(routine.status, "opened")
        item = self.session.query(mysql.ToDo).get(todo.id)
        self.assertEqual(item.status, "opened")
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
        self.assertEqual(item.status, "closed")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/complete"), 202, "updated", False)

        # uncomplete

        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/uncomplete"), 202, "updated", True)
        item = self.session.query(mysql.Routine).get(routine.id)
        self.session.commit()
        self.assertEqual(item.status, "opened")
        self.assertStatusValue(self.api.patch(f"/routine/{routine.id}/task/0/uncomplete"), 202, "updated", False)
