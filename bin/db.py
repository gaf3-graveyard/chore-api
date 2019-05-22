#!/usr/bin/env python

import mysql

mysql.create_database()
data = mysql.MySQL()
mysql.Base.metadata.create_all(data.engine)
