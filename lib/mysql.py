import os
import time

import yaml
import pymysql
import sqlalchemy
import sqlalchemy.orm
import sqlalchemy.ext.declarative
import sqlalchemy.ext.mutable
import flask_jsontools
import sqlalchemy_jsonfield

DATABASE = "nandy"

class MySQL(object):
    """
    Main class for interacting with Nandy in MySQL
    """

    def __init__(self):

        self.engine = sqlalchemy.create_engine(
            f"mysql+pymysql://root@{os.environ['MYSQL_HOST']}:{os.environ['MYSQL_PORT']}/{DATABASE}"
        )
        self.maker = sqlalchemy.orm.sessionmaker(bind=self.engine)

    def session(self):

        return self.maker()


def create_database():

    connection = pymysql.connect(host=os.environ['MYSQL_HOST'], user='root')

    try:

        with connection.cursor() as cursor:
            cursor._defer_warnings = True
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")

        connection.commit()

    finally:

        connection.close()


def drop_database():

    connection = pymysql.connect(host=os.environ['MYSQL_HOST'], user='root')

    try:

        with connection.cursor() as cursor:
            cursor._defer_warnings = True
            cursor.execute(f"DROP DATABASE IF EXISTS {DATABASE}")

        connection.commit()

    finally:

        connection.close()


Base = sqlalchemy.ext.declarative.declarative_base(cls=(flask_jsontools.JsonSerializableBase))

def now():
    return time.time()

class Person(Base):

    __tablename__ = "person"
    
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    name = sqlalchemy.Column(sqlalchemy.String(64), nullable=False)

    sqlalchemy.schema.UniqueConstraint('name', name='label')

    def __repr__(self):
        return "<Person(name='%s')>" % (self.name)


class Template(Base):

    __tablename__ = "template"
    
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    name = sqlalchemy.Column(sqlalchemy.String(128), nullable=False)
    kind = sqlalchemy.Column(sqlalchemy.Enum("routine", "todo", "act"))
    data = sqlalchemy.Column(
        sqlalchemy.ext.mutable.MutableDict.as_mutable(
            sqlalchemy_jsonfield.JSONField(enforce_string=True,enforce_unicode=False)
        ), 
        nullable=False
    )

    sqlalchemy.schema.UniqueConstraint('name', 'kind', name='label')

    def __repr__(self):
        return "<Template(name='%s',kind='%s')>" % (self.name, self.kind)


class Area(Base):

    __tablename__ = "area"
    
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    person_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("person.id"), nullable=False)
    name = sqlalchemy.Column(sqlalchemy.String(64), nullable=False)
    status = sqlalchemy.Column(sqlalchemy.Enum("positive", "negative"), default="positive")
    created = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    updated = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    data = sqlalchemy.Column(
        sqlalchemy.ext.mutable.MutableDict.as_mutable(
            sqlalchemy_jsonfield.JSONField(enforce_string=True,enforce_unicode=False)
        ), 
        nullable=False
    )

    sqlalchemy.schema.UniqueConstraint('name', name='label')

    person = sqlalchemy.orm.relationship("Person") 

    def __repr__(self):
        return "<Area(name='%s')>" % (self.name)


class Act(Base):

    __tablename__ = "act"
    
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    person_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("person.id"), nullable=False)
    name = sqlalchemy.Column(sqlalchemy.String(128), nullable=False)
    status = sqlalchemy.Column(sqlalchemy.Enum("positive", "negative"), default="positive")
    created = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    updated = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    data = sqlalchemy.Column(
        sqlalchemy.ext.mutable.MutableDict.as_mutable(
            sqlalchemy_jsonfield.JSONField(enforce_string=True,enforce_unicode=False)
        ), 
        nullable=False
    )

    person = sqlalchemy.orm.relationship("Person") 

    sqlalchemy.schema.UniqueConstraint('name', 'person_id', 'created', name='label')

    def __repr__(self):
        return "<Act(name='%s',person='%s',created=%s)>" % (self.name, self.person.name, self.created)


class ToDo(Base):

    __tablename__ = "todo"
    
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    person_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("person.id"), nullable=False)
    name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    status = sqlalchemy.Column(sqlalchemy.Enum("opened", "closed"), default="opened")
    created = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    updated = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    data = sqlalchemy.Column(
        sqlalchemy.ext.mutable.MutableDict.as_mutable(
            sqlalchemy_jsonfield.JSONField(enforce_string=True,enforce_unicode=False)
        ), 
        nullable=False
    )

    person = sqlalchemy.orm.relationship("Person") 

    sqlalchemy.schema.UniqueConstraint('name', 'person_id', 'created', name='label')

    def __repr__(self):
        return "<ToDo(name='%s',person='%s',created=%s)>" % (self.name, self.person.name, self.created)


class Routine(Base):

    __tablename__ = "routine"
    
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    person_id = sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("person.id"), nullable=False)
    name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    status = sqlalchemy.Column(sqlalchemy.Enum("opened", "closed"), default="opened")
    created = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    updated = sqlalchemy.Column(sqlalchemy.Integer, default=now)
    data = sqlalchemy.Column(
        sqlalchemy.ext.mutable.MutableDict.as_mutable(
            sqlalchemy_jsonfield.JSONField(enforce_string=True,enforce_unicode=False)
        ), 
        nullable=False
    )

    person = sqlalchemy.orm.relationship("Person") 

    sqlalchemy.schema.UniqueConstraint('name', 'person_id', 'created', name='label')

    def __repr__(self):
        return "<Routine(name='%s',person='%s',created=%s)>" % (self.name, self.person.name, self.created)
