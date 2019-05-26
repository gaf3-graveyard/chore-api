import unittest
import unittest.mock

import os
import time
import json
import pymysql

import mysql


class Sample:

    def __init__(self, session):

        self.session = session

    def person(self, name):

        people = self.session.query(mysql.Person).filter_by(name=name).all()

        if people:
            return people[0]

        person = mysql.Person(name=name)
        self.session.add(person)
        self.session.commit()

        return person

    def template(self, name, kind, data=None):

        if data is None:
            data = {}

        template = mysql.Template(name=name, kind=kind, data=data)
        self.session.add(template)
        self.session.commit()

        return template

    def area(self, person, name, status=None, created=7, updated=8, data=None):

        if data is None:
            data = {}

        area = mysql.Area(
            person_id=self.person(person).id,
            name=name,
            status=status,
            created=created,
            updated=updated,
            data=data
        )
        self.session.add(area)
        self.session.commit()

        return area

    def act(self, person, name="Unit", status=None, created=7, updated=8, data=None):

        if data is None:
            data = {}

        act = mysql.Act(
            person_id=self.person(person).id,
            name=name,
            status=status,
            created=created,
            updated=updated,
            data=data
        )
        self.session.add(act)
        self.session.commit()

        return act

    def todo(self, person, name="Unit", status="opened", created=7, updated=8, data=None):

        if data is None:
            data = {}

        base = {
            "text": "todo it"
        }

        base.update(data)

        todo = mysql.ToDo(
            person_id=self.person(person).id,
            name=name,
            status=status,
            created=created,
            updated=updated,
            data=base
        )

        self.session.add(todo)
        self.session.commit()

        return todo

    def routine(self, person, name="Unit", status="opened", created=7, updated=8, data=None, tasks=None):

        if data is None:
            data = {}

        base = {
            "text": "routine it"
        }

        base.update(data)

        if tasks is not None:
            base["tasks"] = tasks

        routine = mysql.Routine(
            person_id=self.person(person).id,
            name=name,
            status=status,
            created=created,
            updated=updated,
            data=base
        )

        self.session.add(routine)
        self.session.commit()

        return routine


class TestMySQL(unittest.TestCase):

    maxDiff = None

    def setUp(self):

        self.mysql = mysql.MySQL()
        self.session = self.mysql.session()
        mysql.drop_database()
        mysql.create_database()
        mysql.Base.metadata.create_all(self.mysql.engine)

    def tearDown(self):

        self.session.close()
        mysql.drop_database()

    def test_MySQL(self):

        self.assertEqual(str(self.session.get_bind().url), "mysql+pymysql://root@mysql-klotio:3306/nandy")

    def test_Person(self):

        self.session.add(mysql.Person(name="unit", origin="wolverine"))
        self.session.commit()

        person = self.session.query(mysql.Person).one()
        self.assertEqual(str(person), "<Person(name='unit')>")
        self.assertEqual(person.name, "unit")
        self.assertEqual(person.origin, "wolverine")

    def test_Template(self):

        self.session.add(mysql.Template(
            name='Unit Test',
            kind="routine",
            data={"a": 1},
            origin="wolverine"
        ))
        self.session.commit()

        template = self.session.query(mysql.Template).one()
        self.assertEqual(str(template), "<Template(name='Unit Test',kind='routine')>")
        self.assertEqual(template.name, "Unit Test")
        self.assertEqual(template.kind, "routine")
        self.assertEqual(template.data, {"a": 1})
        self.assertEqual(template.origin, "wolverine")

        template.data["a"] = 2
        self.session.commit()
        template = self.session.query(mysql.Template).one()
        self.assertEqual(template.data, {"a": 2})

    @unittest.mock.patch("mysql.time.time", unittest.mock.MagicMock(return_value=7))
    def test_Area(self):

        person = mysql.Person(name="unit")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.Area(
            person_id=person.id,
            name='Unit Test',
            data={"a": 1},
            origin="wolverine"
        ))
        self.session.commit()

        area = self.session.query(mysql.Area).one()
        self.assertEqual(str(area), "<Area(name='Unit Test')>")
        self.assertEqual(area.person_id, person.id)
        self.assertEqual(area.name, "Unit Test")
        self.assertEqual(area.status, "positive")
        self.assertEqual(area.created, 7)
        self.assertEqual(area.updated, 7)
        self.assertEqual(area.data, {"a": 1})
        self.assertEqual(area.origin, "wolverine")

        area.data["a"] = 2
        self.session.commit()
        area = self.session.query(mysql.Area).one()
        self.assertEqual(area.data, {"a": 2})

    @unittest.mock.patch("mysql.time.time", unittest.mock.MagicMock(return_value=7))
    def test_Act(self):

        person = mysql.Person(name="unit")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.Act(
            person_id=person.id,
            name='Unit Test',
            data={"a": 1},
            origin="wolverine"
        ))
        self.session.commit()

        act = self.session.query(mysql.Act).one()
        self.assertEqual(str(act), "<Act(name='Unit Test',person='unit',created=7)>")
        self.assertEqual(act.person_id, person.id)
        self.assertEqual(act.name, "Unit Test")
        self.assertEqual(act.status, "positive")
        self.assertEqual(act.created, 7)
        self.assertEqual(act.updated, 7)
        self.assertEqual(act.data, {"a": 1})
        self.assertEqual(act.origin, "wolverine")

        act.data["a"] = 2
        self.session.commit()
        act = self.session.query(mysql.Act).one()
        self.assertEqual(act.data, {"a": 2})

    @unittest.mock.patch("mysql.time.time", unittest.mock.MagicMock(return_value=7))
    def test_Todo(self):

        person = mysql.Person(name="unit")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.ToDo(
            person_id=person.id,
            name='Unit Test',
            data={"a": 1},
            origin="wolverine"
        ))
        self.session.commit()

        todo = self.session.query(mysql.ToDo).one()
        self.assertEqual(str(todo), "<ToDo(name='Unit Test',person='unit',created=7)>")
        self.assertEqual(todo.person_id, person.id)
        self.assertEqual(todo.name, "Unit Test")
        self.assertEqual(todo.status, "opened")
        self.assertEqual(todo.created, 7)
        self.assertEqual(todo.updated, 7)
        self.assertEqual(todo.data, {"a": 1})
        self.assertEqual(todo.origin, "wolverine")

        todo.data["a"] = 2
        self.session.commit()
        todo = self.session.query(mysql.ToDo).one()
        self.assertEqual(todo.data, {"a": 2})

    @unittest.mock.patch("mysql.time.time", unittest.mock.MagicMock(return_value=7))
    def test_Routine(self):

        person = mysql.Person(name="unit")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.Routine(
            person_id=person.id,
            name='Unit Test',
            data={"a": 1},
            origin="wolverine"
        ))
        self.session.commit()

        routine = self.session.query(mysql.Routine).one()
        self.assertEqual(str(routine), "<Routine(name='Unit Test',person='unit',created=7)>")
        self.assertEqual(routine.person_id, person.id)
        self.assertEqual(routine.name, "Unit Test")
        self.assertEqual(routine.status, "opened")
        self.assertEqual(routine.created, 7)
        self.assertEqual(routine.updated, 7)
        self.assertEqual(routine.data, {"a": 1})
        self.assertEqual(routine.origin, "wolverine")

        routine.data["a"] = 2
        self.session.commit()
        routine = self.session.query(mysql.Routine).one()
        self.assertEqual(routine.data, {"a": 2})
