from sqlite_utils import cli, Database
from sqlite_utils.db import Index, ForeignKey
from click.testing import CliRunner
import json
import os
import pytest
import sqlite3

from .utils import collapse_whitespace


CREATE_TABLES = """
create table Gosh (c1 text, c2 text, c3 text);
create table Gosh2 (c1 text, c2 text, c3 text);
"""


@pytest.fixture
def db_path(tmpdir):
    path = str(tmpdir / "test.db")
    db = sqlite3.connect(path)
    db.executescript(CREATE_TABLES)
    return path


def test_tables(db_path):
    result = CliRunner().invoke(cli.cli, ["tables", db_path])
    assert '[{"table": "Gosh"},\n {"table": "Gosh2"}]' == result.output.strip()


def test_tables_fts4(db_path):
    Database(db_path)["Gosh"].enable_fts(["c2"], fts_version="FTS4")
    result = CliRunner().invoke(cli.cli, ["tables", "--fts4", db_path])
    assert '[{"table": "Gosh_fts"}]' == result.output.strip()


def test_tables_fts5(db_path):
    Database(db_path)["Gosh"].enable_fts(["c2"], fts_version="FTS5")
    result = CliRunner().invoke(cli.cli, ["tables", "--fts5", db_path])
    assert '[{"table": "Gosh_fts"}]' == result.output.strip()


def test_tables_counts_and_columns(db_path):
    db = Database(db_path)
    with db.conn:
        db["lots"].insert_all([{"id": i, "age": i + 1} for i in range(30)])
    result = CliRunner().invoke(cli.cli, ["tables", "--counts", "--columns", db_path])
    assert (
        '[{"table": "Gosh", "count": 0, "columns": ["c1", "c2", "c3"]},\n'
        ' {"table": "Gosh2", "count": 0, "columns": ["c1", "c2", "c3"]},\n'
        ' {"table": "lots", "count": 30, "columns": ["id", "age"]}]'
    ) == result.output.strip()


def test_tables_counts_and_columns_csv(db_path):
    db = Database(db_path)
    with db.conn:
        db["lots"].insert_all([{"id": i, "age": i + 1} for i in range(30)])
    result = CliRunner().invoke(
        cli.cli, ["tables", "--counts", "--columns", "--csv", db_path]
    )
    assert (
        "table,count,columns\n"
        'Gosh,0,"c1\n'
        "c2\n"
        'c3"\n'
        'Gosh2,0,"c1\n'
        "c2\n"
        'c3"\n'
        'lots,30,"id\n'
        'age"'
    ) == result.output.strip()


@pytest.mark.parametrize(
    "fmt,expected",
    [
        (
            "simple",
            (
                "c1     c2     c3\n"
                "-----  -----  ----------\n"
                "verb0  noun0  adjective0\n"
                "verb1  noun1  adjective1\n"
                "verb2  noun2  adjective2\n"
                "verb3  noun3  adjective3"
            ),
        ),
        (
            "rst",
            (
                "=====  =====  ==========\n"
                "c1     c2     c3\n"
                "=====  =====  ==========\n"
                "verb0  noun0  adjective0\n"
                "verb1  noun1  adjective1\n"
                "verb2  noun2  adjective2\n"
                "verb3  noun3  adjective3\n"
                "=====  =====  =========="
            ),
        ),
    ],
)
def test_output_table(db_path, fmt, expected):
    db = Database(db_path)
    with db.conn:
        db["rows"].insert_all(
            [
                {
                    "c1": "verb{}".format(i),
                    "c2": "noun{}".format(i),
                    "c3": "adjective{}".format(i),
                }
                for i in range(4)
            ]
        )
    result = CliRunner().invoke(cli.cli, ["rows", db_path, "rows", "-t", "-f", fmt])
    assert 0 == result.exit_code
    assert expected == result.output.strip()


def test_create_index(db_path):
    db = Database(db_path)
    assert [] == db["Gosh"].indexes
    result = CliRunner().invoke(cli.cli, ["create-index", db_path, "Gosh", "c1"])
    assert 0 == result.exit_code
    assert [
        Index(
            seq=0, name="idx_Gosh_c1", unique=0, origin="c", partial=0, columns=["c1"]
        )
    ] == db["Gosh"].indexes
    # Try with a custom name
    result = CliRunner().invoke(
        cli.cli, ["create-index", db_path, "Gosh", "c2", "--name", "blah"]
    )
    assert 0 == result.exit_code
    assert [
        Index(seq=0, name="blah", unique=0, origin="c", partial=0, columns=["c2"]),
        Index(
            seq=1, name="idx_Gosh_c1", unique=0, origin="c", partial=0, columns=["c1"]
        ),
    ] == db["Gosh"].indexes
    # Try a two-column unique index
    create_index_unique_args = [
        "create-index",
        db_path,
        "Gosh2",
        "c1",
        "c2",
        "--unique",
    ]
    result = CliRunner().invoke(cli.cli, create_index_unique_args)
    assert 0 == result.exit_code
    assert [
        Index(
            seq=0,
            name="idx_Gosh2_c1_c2",
            unique=1,
            origin="c",
            partial=0,
            columns=["c1", "c2"],
        )
    ] == db["Gosh2"].indexes
    # Trying to create the same index should fail
    assert 0 != CliRunner().invoke(cli.cli, create_index_unique_args).exit_code
    # ... unless we use --if-not-exists
    assert (
        0
        == CliRunner()
        .invoke(cli.cli, create_index_unique_args + ["--if-not-exists"])
        .exit_code
    )


@pytest.mark.parametrize(
    "col_name,col_type,expected_schema",
    (
        ("text", "TEXT", "CREATE TABLE [dogs] ( [name] TEXT , [text] TEXT)"),
        (
            "integer",
            "INTEGER",
            "CREATE TABLE [dogs] ( [name] TEXT , [integer] INTEGER)",
        ),
        ("float", "FLOAT", "CREATE TABLE [dogs] ( [name] TEXT , [float] FLOAT)"),
        ("blob", "blob", "CREATE TABLE [dogs] ( [name] TEXT , [blob] BLOB)"),
        ("default", None, "CREATE TABLE [dogs] ( [name] TEXT , [default] TEXT)"),
    ),
)
def test_add_column(db_path, col_name, col_type, expected_schema):
    db = Database(db_path)
    db.create_table("dogs", {"name": str})
    assert "CREATE TABLE [dogs] ( [name] TEXT )" == collapse_whitespace(
        db["dogs"].schema
    )
    args = ["add-column", db_path, "dogs", col_name]
    if col_type is not None:
        args.append(col_type)
    assert 0 == CliRunner().invoke(cli.cli, args).exit_code
    assert expected_schema == collapse_whitespace(db["dogs"].schema)


def test_add_foreign_key(db_path):
    db = Database(db_path)
    db["authors"].insert_all(
        [{"id": 1, "name": "Sally"}, {"id": 2, "name": "Asheesh"}], pk="id"
    )
    db["books"].insert_all(
        [
            {"title": "Hedgehogs of the world", "author_id": 1},
            {"title": "How to train your wolf", "author_id": 2},
        ]
    )
    assert (
        0
        == CliRunner()
        .invoke(
            cli.cli, ["add-foreign-key", db_path, "books", "author_id", "authors", "id"]
        )
        .exit_code
    )
    assert [
        ForeignKey(
            table="books", column="author_id", other_table="authors", other_column="id"
        )
    ] == db["books"].foreign_keys
    # Error if we try to add it twice:
    result = CliRunner().invoke(
        cli.cli, ["add-foreign-key", db_path, "books", "author_id", "authors", "id"]
    )

    assert 0 != result.exit_code
    assert (
        "Error: Foreign key already exists for author_id => authors.id"
        == result.output.strip()
    )
    # Error if we try against an invalid cgolumn
    result = CliRunner().invoke(
        cli.cli, ["add-foreign-key", db_path, "books", "author_id", "authors", "bad"]
    )
    assert 0 != result.exit_code
    assert "Error: No such column: authors.bad" == result.output.strip()


def test_enable_fts(db_path):
    assert None == Database(db_path)["Gosh"].detect_fts()
    result = CliRunner().invoke(
        cli.cli, ["enable-fts", db_path, "Gosh", "c1", "--fts4"]
    )
    assert 0 == result.exit_code
    assert "Gosh_fts" == Database(db_path)["Gosh"].detect_fts()


def test_populate_fts(db_path):
    Database(db_path)["Gosh"].insert_all([{"c1": "baz"}])
    exit_code = (
        CliRunner()
        .invoke(cli.cli, ["enable-fts", db_path, "Gosh", "c1", "--fts4"])
        .exit_code
    )
    assert 0 == exit_code

    def search(q):
        return (
            Database(db_path)
            .conn.execute("select c1 from Gosh_fts where c1 match ?", [q])
            .fetchall()
        )

    assert [("baz",)] == search("baz")
    Database(db_path)["Gosh"].insert_all([{"c1": "martha"}])
    assert [] == search("martha")
    exit_code = (
        CliRunner().invoke(cli.cli, ["populate-fts", db_path, "Gosh", "c1"]).exit_code
    )
    assert 0 == exit_code
    assert [("martha",)] == search("martha")


def test_vacuum(db_path):
    result = CliRunner().invoke(cli.cli, ["vacuum", db_path])
    assert 0 == result.exit_code


def test_optimize(db_path):
    db = Database(db_path)
    with db.conn:
        for table in ("Gosh", "Gosh2"):
            db[table].insert_all(
                [
                    {
                        "c1": "verb{}".format(i),
                        "c2": "noun{}".format(i),
                        "c3": "adjective{}".format(i),
                    }
                    for i in range(10000)
                ]
            )
        db["Gosh"].enable_fts(["c1", "c2", "c3"], fts_version="FTS4")
        db["Gosh2"].enable_fts(["c1", "c2", "c3"], fts_version="FTS5")
    size_before_optimize = os.stat(db_path).st_size
    result = CliRunner().invoke(cli.cli, ["optimize", db_path])
    assert 0 == result.exit_code
    size_after_optimize = os.stat(db_path).st_size
    assert size_after_optimize < size_before_optimize
    # Sanity check that --no-vacuum doesn't throw errors:
    result = CliRunner().invoke(cli.cli, ["optimize", "--no-vacuum", db_path])
    assert 0 == result.exit_code


def test_insert_simple(tmpdir):
    json_path = str(tmpdir / "dog.json")
    db_path = str(tmpdir / "dogs.db")
    open(json_path, "w").write(json.dumps({"name": "Cleo", "age": 4}))
    result = CliRunner().invoke(cli.cli, ["insert", db_path, "dogs", json_path])
    assert 0 == result.exit_code
    assert [{"age": 4, "name": "Cleo"}] == Database(db_path).execute_returning_dicts(
        "select * from dogs"
    )
    db = Database(db_path)
    assert ["dogs"] == db.table_names()
    assert [] == db["dogs"].indexes


def test_insert_with_primary_key(db_path, tmpdir):
    json_path = str(tmpdir / "dog.json")
    open(json_path, "w").write(json.dumps({"id": 1, "name": "Cleo", "age": 4}))
    result = CliRunner().invoke(
        cli.cli, ["insert", db_path, "dogs", json_path, "--pk", "id"]
    )
    assert 0 == result.exit_code
    assert [{"id": 1, "age": 4, "name": "Cleo"}] == Database(
        db_path
    ).execute_returning_dicts("select * from dogs")
    db = Database(db_path)
    assert ["id"] == db["dogs"].pks


def test_insert_multiple_with_primary_key(db_path, tmpdir):
    json_path = str(tmpdir / "dogs.json")
    dogs = [{"id": i, "name": "Cleo {}".format(i), "age": i + 3} for i in range(1, 21)]
    open(json_path, "w").write(json.dumps(dogs))
    result = CliRunner().invoke(
        cli.cli, ["insert", db_path, "dogs", json_path, "--pk", "id"]
    )
    assert 0 == result.exit_code
    db = Database(db_path)
    assert dogs == db.execute_returning_dicts("select * from dogs order by id")
    assert ["id"] == db["dogs"].pks


def test_insert_newline_delimited(db_path):
    result = CliRunner().invoke(
        cli.cli,
        ["insert", db_path, "from_json_nl", "-", "--nl"],
        input='{"foo": "bar", "n": 1}\n{"foo": "baz", "n": 2}',
    )
    assert 0 == result.exit_code, result.output
    db = Database(db_path)
    assert [
        {"foo": "bar", "n": 1},
        {"foo": "baz", "n": 2},
    ] == db.execute_returning_dicts("select foo, n from from_json_nl")


def test_upsert(db_path, tmpdir):
    test_insert_multiple_with_primary_key(db_path, tmpdir)
    json_path = str(tmpdir / "upsert.json")
    db = Database(db_path)
    assert 20 == db["dogs"].count
    upsert_dogs = [
        {"id": 1, "name": "Upserted 1", "age": 4},
        {"id": 2, "name": "Upserted 2", "age": 4},
        {"id": 21, "name": "Fresh insert 21", "age": 6},
    ]
    open(json_path, "w").write(json.dumps(upsert_dogs))
    result = CliRunner().invoke(
        cli.cli, ["upsert", db_path, "dogs", json_path, "--pk", "id"]
    )
    assert 0 == result.exit_code
    assert 21 == db["dogs"].count
    assert upsert_dogs == db.execute_returning_dicts(
        "select * from dogs where id in (1, 2, 21) order by id"
    )


def test_query_csv(db_path):
    db = Database(db_path)
    with db.conn:
        db["dogs"].insert_all(
            [
                {"id": 1, "age": 4, "name": "Cleo"},
                {"id": 2, "age": 2, "name": "Pancakes"},
            ]
        )
    result = CliRunner().invoke(
        cli.cli, [db_path, "select id, name, age from dogs", "--csv"]
    )
    assert 0 == result.exit_code
    assert "id,name,age\n1,Cleo,4\n2,Pancakes,2\n" == result.output
    # Test the no-headers option:
    result = CliRunner().invoke(
        cli.cli, [db_path, "select id, name, age from dogs", "--no-headers", "--csv"]
    )
    assert "1,Cleo,4\n2,Pancakes,2\n" == result.output


_all_query = "select id, name, age from dogs"
_one_query = "select id, name, age from dogs where id = 1"


@pytest.mark.parametrize(
    "sql,args,expected",
    [
        (
            _all_query,
            [],
            '[{"id": 1, "name": "Cleo", "age": 4},\n {"id": 2, "name": "Pancakes", "age": 2}]',
        ),
        (
            _all_query,
            ["--nl"],
            '{"id": 1, "name": "Cleo", "age": 4}\n{"id": 2, "name": "Pancakes", "age": 2}',
        ),
        (_all_query, ["--arrays"], '[[1, "Cleo", 4],\n [2, "Pancakes", 2]]'),
        (_all_query, ["--arrays", "--nl"], '[1, "Cleo", 4]\n[2, "Pancakes", 2]'),
        (_one_query, [], '[{"id": 1, "name": "Cleo", "age": 4}]'),
        (_one_query, ["--nl"], '{"id": 1, "name": "Cleo", "age": 4}'),
        (_one_query, ["--arrays"], '[[1, "Cleo", 4]]'),
        (_one_query, ["--arrays", "--nl"], '[1, "Cleo", 4]'),
    ],
)
def test_query_json(db_path, sql, args, expected):
    db = Database(db_path)
    with db.conn:
        db["dogs"].insert_all(
            [
                {"id": 1, "age": 4, "name": "Cleo"},
                {"id": 2, "age": 2, "name": "Pancakes"},
            ]
        )
    result = CliRunner().invoke(cli.cli, [db_path, sql] + args)
    assert expected == result.output.strip()


@pytest.mark.parametrize(
    "args,expected",
    [
        (
            [],
            '[{"id": 1, "name": "Cleo", "age": 4},\n {"id": 2, "name": "Pancakes", "age": 2}]',
        ),
        (
            ["--nl"],
            '{"id": 1, "name": "Cleo", "age": 4}\n{"id": 2, "name": "Pancakes", "age": 2}',
        ),
        (["--arrays"], '[[1, "Cleo", 4],\n [2, "Pancakes", 2]]'),
        (["--arrays", "--nl"], '[1, "Cleo", 4]\n[2, "Pancakes", 2]'),
    ],
)
def test_rows(db_path, args, expected):
    db = Database(db_path)
    with db.conn:
        db["dogs"].insert_all(
            [
                {"id": 1, "age": 4, "name": "Cleo"},
                {"id": 2, "age": 2, "name": "Pancakes"},
            ],
            column_order=("id", "name", "age"),
        )
    result = CliRunner().invoke(cli.cli, ["rows", db_path, "dogs"] + args)
    assert expected == result.output.strip()
