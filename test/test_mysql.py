import unittest

import os
import time
import json
import pymysql

import mysql


class Sample:

    def __init__(self, session):

        self.session = session

    def person(self, name, email=None):

        if email is None:
            email = name

        person = mysql.Person(name=name, email=email)
        self.session.add(person)
        self.session.commit()

        return person

    def area(self, name, status=None, updated=7, data=None):

        if status is None:
            status = name

        if data is None:
            data = {}

        area = mysql.Area(name=name, status=status, updated=updated, data=data)
        self.session.add(area)
        self.session.commit()

        return area

    def template(self, name, kind, data=None):

        if data is None:
            data = {}

        template = mysql.Template(name=name, kind=kind, data=data)
        self.session.add(template)
        self.session.commit()

        return template

    def routine(self, person, name="Unit", status="started", created=7, updated=8, data=None, tasks=None):

        if data is None:
            data = {}

        base = {
            "text": "routine it",
            "language": "en-us"
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

    def todo(self, person, name="Unit", status="needed", created=7, updated=8, data=None):

        if data is None:
            data = {}

        base = {
            "text": "todo it",
            "language": "en-us"
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

    def act(self, person, name="Unit", value="positive", created=7, data=None):

        if data is None:
            data = {}

        act = mysql.Act(
            person_id=self.person(person).id,
            name=name,
            value=value,
            created=created,
            data=data
        )
        self.session.add(act)
        self.session.commit()

        return act


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

        self.assertEqual(str(self.session.get_bind().url), "mysql+pymysql://root@mysql-klotio:3306/nandy_chore")

    def test_Person(self):

        self.session.add(mysql.Person(name="unit", email="test"))
        self.session.commit()

        person = self.session.query(mysql.Person).one()
        self.assertEqual(str(person), "<Person(name='unit')>")
        self.assertEqual(person.name, "unit")
        self.assertEqual(person.email, "test")
        
    def test_Area(self):

        self.session.add(mysql.Area(
            name='Unit Test',
            status="messy",
            updated=8,
            data={"a": 1}
        ))
        self.session.commit()

        area = self.session.query(mysql.Area).one()
        self.assertEqual(str(area), "<Area(name='Unit Test')>")
        self.assertEqual(area.name, "Unit Test")
        self.assertEqual(area.status, "messy")
        self.assertEqual(area.updated, 8)
        self.assertEqual(area.data, {"a": 1})

        area.data["a"] = 2
        self.session.commit()
        area = self.session.query(mysql.Area).one()
        self.assertEqual(area.data, {"a": 2})

    def test_Template(self):

        self.session.add(mysql.Template(
            name='Unit Test',
            kind="routine",
            data={"a": 1}
        ))
        self.session.commit()

        template = self.session.query(mysql.Template).one()
        self.assertEqual(str(template), "<Template(name='Unit Test',kind='routine')>")
        self.assertEqual(template.name, "Unit Test")
        self.assertEqual(template.kind, "routine")
        self.assertEqual(template.data, {"a": 1})

        template.data["a"] = 2
        self.session.commit()
        template = self.session.query(mysql.Template).one()
        self.assertEqual(template.data, {"a": 2})

    def test_Routine(self):

        person = mysql.Person(name="unit", email="test")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.Routine(
            person_id=person.id,
            name='Unit Test',
            status="started",
            created=7,
            updated=8,
            data={"a": 1}
        ))
        self.session.commit()

        routine = self.session.query(mysql.Routine).one()
        self.assertEqual(str(routine), "<Routine(name='Unit Test',person='unit',created=7)>")
        self.assertEqual(routine.person_id, person.id)
        self.assertEqual(routine.name, "Unit Test")
        self.assertEqual(routine.status, "started")
        self.assertEqual(routine.created, 7)
        self.assertEqual(routine.updated, 8)
        self.assertEqual(routine.data, {"a": 1})

        routine.data["a"] = 2
        self.session.commit()
        routine = self.session.query(mysql.Routine).one()
        self.assertEqual(routine.data, {"a": 2})

    def test_Todo(self):

        person = mysql.Person(name="unit", email="test")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.ToDo(
            person_id=person.id,
            name='Unit Test',
            status="needed",
            created=7,
            updated=8,
            data={"a": 1}
        ))
        self.session.commit()

        todo = self.session.query(mysql.ToDo).one()
        self.assertEqual(str(todo), "<ToDo(name='Unit Test',person='unit',created=7)>")
        self.assertEqual(todo.person_id, person.id)
        self.assertEqual(todo.name, "Unit Test")
        self.assertEqual(todo.status, "needed")
        self.assertEqual(todo.created, 7)
        self.assertEqual(todo.updated, 8)
        self.assertEqual(todo.data, {"a": 1})

        todo.data["a"] = 2
        self.session.commit()
        todo = self.session.query(mysql.ToDo).one()
        self.assertEqual(todo.data, {"a": 2})

    def test_Act(self):

        person = mysql.Person(name="unit", email="test")
        self.session.add(person)
        self.session.commit()

        self.session.add(mysql.Act(
            person_id=person.id,
            name='Unit Test',
            value="positive",
            created=7,
            data={"a": 1}
        ))
        self.session.commit()

        act = self.session.query(mysql.Act).one()
        self.assertEqual(str(act), "<Act(name='Unit Test',person='unit',created=7)>")
        self.assertEqual(act.person_id, person.id)
        self.assertEqual(act.name, "Unit Test")
        self.assertEqual(act.value, "positive")
        self.assertEqual(act.created, 7)
        self.assertEqual(act.data, {"a": 1})

        act.data["a"] = 2
        self.session.commit()
        act = self.session.query(mysql.Act).one()
        self.assertEqual(act.data, {"a": 2})