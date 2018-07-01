import psycopg2 as ps
import pandas as pd
import numpy
import martha as mh
import boto3
from .aws import extractBucketName
from .aws import fetchS3

def queryPostgres(host, port, user, password, database, query):
    '''
    Submit a blocking query to Postgres
    -----------
    DETAILS
    -----------
    This function will send a query to a Postgres compliant database (including Amazon Redshift and Amazon Aurora).
    The query will wait for a response with the data which means any queries will need to resolve within 5 minutes if
    invoking on as a Lambda Function (or 30 seconds if invoking the lambda through HTTP).
    -----------
    PARAMS
    -----------
    host : The hostname of the database to connec todo
    port : The port that accepts connections
    user : username that has permission to execute queries
    password : The password for authentication
    database : The database one the Postgres instance to run the query against
    query : The query to execute
    '''
    try:
        conn = ps.connect("dbname='" + database + "' user='" + user + "' host='" + host + "' port='" + port + "' password='" + password + "'")
        cur = conn.cursor()
        cur.execute(query)

        columns = []
        for i in range(len(cur.description)):
            columns.append(cur.description[i].name)
            pass

        rows = cur.fetchall()
        data = pd.DataFrame(rows)
        data.columns = columns
        conn.close
        return data
    except ValueError as e:
         raise Exception("ValueError: Most likely no rows were returned from database.")

def createFieldReplacement(repeats):
        repeats = repeats - 1
        fieldReplacement = "%s, "
        fieldReplacement = fieldReplacement * repeats
        fieldReplacement = fieldReplacement + "%s"
        fieldReplacement = "(" + fieldReplacement + ")"
        return fieldReplacement

def insertToPostgres(host, port, username, password, database, table, data, columns, upsertPrimaryKey = None):
    try:
        data = data.where((pd.notnull(data)), None)
        rowsToInsert = len(data)
        fieldReplacement = createFieldReplacement(len(data.columns))
        conn = ps.connect("dbname='" + database + "' user='" + username + "' host='" + host + "' port='" + port + "' password='" + password + "'")
        cur = conn.cursor()
        allRowSql = bytes(b"INSERT INTO " + table.encode() + b" (" + mh.cleanUpString(str(data.columns.values.tolist()), ["[", "]", "'"], {"'" : ""}).encode() + b") VALUES ")

        for i in range(rowsToInsert):
            row = data.iloc[i].values.tolist()
            if i == (rowsToInsert - 1):
                rowSql = cur.mogrify(fieldReplacement, (row))
            else:
                rowSql = cur.mogrify(fieldReplacement, (row)) + b","

            allRowSql = allRowSql + rowSql

        if upsertPrimaryKey != None:
            baseUpsert = b" ON CONFLICT (" + upsertPrimaryKey.encode() + b") DO UPDATE SET "

            allRowSql = allRowSql + baseUpsert

            for i in range(len(data.columns)):
                if i == (len(data.columns) - 1):
                    columnUpsert = data.columns.values.tolist()[i].encode() + b" = EXCLUDED." + data.columns.values.tolist()[i].encode()
                    allRowSql = allRowSql + columnUpsert
                else:
                    columnUpsert = data.columns.values.tolist()[i].encode() + b" = EXCLUDED." + data.columns.values.tolist()[i].encode() + b","
                    allRowSql = allRowSql + columnUpsert

        cur.execute(allRowSql)
        conn.commit()
        conn.close()
        results = {"columns" : len(data.columns), "rows" : len(data)}
        return results
    except Exception as e:
        conn.close()
        raise Exception(str(e))


def getExecutionStatus(executionId, client):
    execution = client.get_query_execution(QueryExecutionId = executionId)
    outputLocation = execution['QueryExecution']['ResultConfiguration']['OutputLocation']
    status = execution['QueryExecution']['Status']['State']
    return status, outputLocation

def queryAthena(access_key, access_secret, query, resultLocation):
    client = boto3.client('athena', aws_access_key_id = access_key, aws_secret_access_key = access_secret)
    queryRequest = client.start_query_execution(QueryString = query, ResultConfiguration = {'OutputLocation' : resultLocation})

    executionStatus = getExecutionStatus(str(queryRequest['QueryExecutionId']), client)
    status = executionStatus[0]

    while status == 'RUNNING':
        executionStatus = getExecutionStatus(str(queryRequest['QueryExecutionId']), client)
        status = executionStatus[0]

    resultDataLocation = extractBucketName(executionStatus[1])
    resultData = fetchS3(access_key, access_secret, resultDataLocation[0], resultDataLocation[1][0])
    return resultData
