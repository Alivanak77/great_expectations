import pytest

import sys
from freezegun import freeze_time

from great_expectations.core import ExpectationConfiguration, dataAssetIdentifierSchema, expectationSuiteSchema, \
    namespaceAwareExpectationSuiteSchema
from great_expectations.data_context.store import ExpectationsStore
from great_expectations.data_context.types.base import DataContextConfig

try:
    from unittest import mock
except ImportError:
    import mock

import os
import shutil
import json
from collections import OrderedDict
from ruamel.yaml import YAML

from great_expectations.exceptions import DataContextError
from great_expectations.data_context import (
    ConfigOnlyDataContext,
    DataContext,
    ExplorerDataContext,
)
from great_expectations.data_context.util import safe_mmkdir
from great_expectations.data_context.types import (
    DataAssetIdentifier,
    ExpectationSuiteIdentifier,
)
from great_expectations.util import (
    gen_directory_tree_str,
)

yaml = YAML()


@pytest.fixture()
def parameterized_expectation_suite():
    with open("tests/test_fixtures/expectation_suites/parameterized_expectation_suite_fixture.json", "r") as suite:
        return json.load(suite)


def test_create_duplicate_expectation_suite(titanic_data_context):
    # create new expectation suite
    assert titanic_data_context.create_expectation_suite(data_asset_name="titanic", expectation_suite_name="test_create_expectation_suite")
    # attempt to create expectation suite with name that already exists on data asset
    with pytest.raises(DataContextError):
        titanic_data_context.create_expectation_suite(data_asset_name="titanic",
                                                      expectation_suite_name="test_create_expectation_suite")
    # create expectation suite with name that already exists on data asset, but pass overwrite_existing=True
    assert titanic_data_context.create_expectation_suite(data_asset_name="titanic", expectation_suite_name="test_create_expectation_suite", overwrite_existing=True)


def test_list_available_data_asset_names(empty_data_context, filesystem_csv):
    empty_data_context.add_datasource("my_datasource",
                                      module_name="great_expectations.datasource",
                                      class_name="PandasDatasource",
                                      base_directory=str(filesystem_csv))
    available_asset_names = empty_data_context.get_available_data_asset_names()
    available_asset_names["my_datasource"]["default"] = set(available_asset_names["my_datasource"]["default"])

    assert available_asset_names == {
        "my_datasource": {
            "default": {"f1", "f2", "f3"}
        }
    }


def test_list_expectation_suite_keys(data_context):
    assert data_context.list_expectation_suite_keys() == [
        ExpectationSuiteIdentifier(
            data_asset_name=DataAssetIdentifier(
                "mydatasource",
                "mygenerator",
                "my_dag_node",
            ),
            expectation_suite_name="default"
        )
    ]


def test_get_existing_expectation_suite(data_context):
    expectation_suite = data_context.get_expectation_suite('mydatasource/mygenerator/my_dag_node', 'default')
    assert expectation_suite.data_asset_name == DataAssetIdentifier.from_tuple(('mydatasource', 'mygenerator',
                                                                               'my_dag_node'))
    assert expectation_suite.expectation_suite_name == 'default'
    assert len(expectation_suite.expectations) == 2


def test_get_new_expectation_suite(data_context):
    expectation_suite = data_context.create_expectation_suite('this_data_asset_does_not_exist', 'default')
    assert expectation_suite.data_asset_name == DataAssetIdentifier.from_tuple(
        ('mydatasource', 'mygenerator', 'this_data_asset_does_not_exist'))
    assert expectation_suite.expectation_suite_name == 'default'
    assert len(expectation_suite.expectations) == 0


def test_save_expectation_suite(data_context):
    expectation_suite = data_context.create_expectation_suite('this_data_asset_config_does_not_exist', 'default')
    expectation_suite.expectations.append(ExpectationConfiguration(
        expectation_type="expect_table_row_count_to_equal",
        kwargs={
            "value": 10
        }))
    data_context.save_expectation_suite(expectation_suite)
    expectation_suite_saved = data_context.get_expectation_suite('this_data_asset_config_does_not_exist')
    assert expectation_suite.expectations == expectation_suite_saved.expectations


def test_compile(data_context):
    data_context._compile()
    assert data_context._compiled_parameters == {
        'raw': {
            'urn:great_expectations:validations:mydatasource/mygenerator/source_diabetes_data:default:expectations:expect_column_unique_value_count_to_be_between:columns:patient_nbr:result:observed_value',
            'urn:great_expectations:validations:mydatasource/mygenerator/source_patient_data:default:expectations:expect_table_row_count_to_equal:result:observed_value'
            },
        'data_assets': {
            DataAssetIdentifier(
                datasource='mydatasource',
                generator='mygenerator',
                generator_asset='source_diabetes_data'
            ): {
                'default': {
                    'expect_column_unique_value_count_to_be_between': {
                        'columns': {
                            'patient_nbr': {
                                'result': {
                                    'urn:great_expectations:validations:mydatasource/mygenerator/source_diabetes_data:default:expectations:expect_column_unique_value_count_to_be_between:columns:patient_nbr:result:observed_value'
                                }
                            }
                        }
                    }
                }
            },
            DataAssetIdentifier(
                datasource='mydatasource',
                generator='mygenerator',
                generator_asset='source_patient_data'
            ): {
                'default': {
                    'expect_table_row_count_to_equal': {
                        'result': {
                            'urn:great_expectations:validations:mydatasource/mygenerator/source_patient_data:default:expectations:expect_table_row_count_to_equal:result:observed_value'
                        }
                    }
                }
            }
        }
    }

def test_normalize_data_asset_names_error(data_context):
    with pytest.raises(DataContextError) as exc:
        data_context.normalize_data_asset_name("this/should/never/work/because/it/is/so/long")
    assert "found too many components using delimiter '/'" in exc.value.message


def test_normalize_data_asset_names_delimiters(empty_data_context, filesystem_csv):
    empty_data_context.add_datasource("my_datasource",
                                    module_name="great_expectations.datasource",
                                    class_name="PandasDatasource",
                                    base_directory=str(filesystem_csv))
    data_context = empty_data_context

    data_context.data_asset_name_delimiter = '.'
    assert data_context.normalize_data_asset_name("my_datasource.default.f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")
    assert data_context.normalize_data_asset_name("my_datasource.default.f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    data_context.data_asset_name_delimiter = '/'
    assert data_context.normalize_data_asset_name("my_datasource/default/f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    with pytest.raises(DataContextError) as exc:
        data_context.data_asset_name_delimiter = "$"
    assert "Invalid delimiter" in exc.value.message

    with pytest.raises(DataContextError) as exc:
        data_context.data_asset_name_delimiter = "//"
    assert "Invalid delimiter" in exc.value.message


def test_normalize_data_asset_names_conditions(empty_data_context, filesystem_csv, tmp_path_factory):
    # If no datasource is configured, nothing should be allowed to normalize:
    with pytest.raises(DataContextError) as exc:
        empty_data_context.normalize_data_asset_name("f1")
    assert "No datasource configured" in exc.value.message

    with pytest.raises(DataContextError) as exc:
        empty_data_context.normalize_data_asset_name("my_datasource/f1")
    assert "No datasource configured" in exc.value.message

    with pytest.raises(DataContextError) as exc:
        empty_data_context.normalize_data_asset_name("my_datasource/default/f1")
    assert "no configured datasource" in exc.value.message

    ###
    # Add a datasource
    ###
    empty_data_context.add_datasource("my_datasource",
                                    module_name="great_expectations.datasource",
                                    class_name="PandasDatasource",
                                    base_directory=str(filesystem_csv))
    data_context = empty_data_context

    # We can now reference existing or available data asset namespaces using
    # a the data_asset_name; the datasource name and data_asset_name or all
    # three components of the normalized data asset name
    assert data_context.normalize_data_asset_name("f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    assert data_context.normalize_data_asset_name("my_datasource/f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    assert data_context.normalize_data_asset_name("my_datasource/default/f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    # With only one datasource and generator configured, we
    # can create new namespaces at the generator asset level easily:
    assert data_context.normalize_data_asset_name("f5") == \
        DataAssetIdentifier("my_datasource", "default", "f5")

    # We can also be more explicit in creating new namespaces at the generator asset level:
    assert data_context.normalize_data_asset_name("my_datasource/f6") == \
        DataAssetIdentifier("my_datasource", "default", "f6")

    assert data_context.normalize_data_asset_name("my_datasource/default/f7") == \
        DataAssetIdentifier("my_datasource", "default", "f7")

    # However, we cannot create against nonexisting datasources or generators:
    with pytest.raises(DataContextError) as exc:
        data_context.normalize_data_asset_name("my_fake_datasource/default/f7")
    assert "no configured datasource 'my_fake_datasource' with generator 'default'" in exc.value.message

    with pytest.raises(DataContextError) as exc:
        data_context.normalize_data_asset_name("my_datasource/my_fake_generator/f7")
    assert "no configured datasource 'my_datasource' with generator 'my_fake_generator'" in exc.value.message

    ###
    # Add a second datasource
    ###

    second_datasource_basedir = str(tmp_path_factory.mktemp("test_normalize_data_asset_names_conditions_single_name"))
    with open(os.path.join(second_datasource_basedir, "f3.tsv"), "w") as outfile:
        outfile.write("\n\n\n")
    with open(os.path.join(second_datasource_basedir, "f4.tsv"), "w") as outfile:
        outfile.write("\n\n\n")
    data_context.add_datasource("my_second_datasource",
                                    module_name="great_expectations.datasource",
                                    class_name="PandasDatasource",
                                    base_directory=second_datasource_basedir)

    # We can still reference *unambiguous* data_asset_names:
    assert data_context.normalize_data_asset_name("f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    assert data_context.normalize_data_asset_name("f4") == \
        DataAssetIdentifier("my_second_datasource", "default", "f4")

    # However, single-name resolution will fail with ambiguous entries
    with pytest.raises(DataContextError) as exc:
        data_context.normalize_data_asset_name("f3")
    assert "Ambiguous data_asset_name 'f3'. Multiple candidates found" in exc.value.message

    # Two-name resolution still works since generators are not ambiguous in that case
    assert data_context.normalize_data_asset_name("my_datasource/f3") == \
        DataAssetIdentifier("my_datasource", "default", "f3")

    # We can also create new namespaces using only two components since that is not ambiguous
    assert data_context.normalize_data_asset_name("my_datasource/f9") == \
        DataAssetIdentifier("my_datasource", "default", "f9")

    # However, we cannot create new names using only a single component
    with pytest.raises(DataContextError) as exc:
        data_context.normalize_data_asset_name("f10")
    assert "Ambiguous data_asset_name: no existing data_asset has the provided name" in exc.value.message

    ###
    # Add a second generator to one datasource
    ###
    my_datasource = data_context.get_datasource("my_datasource")
    my_datasource.add_generator("in_memory_generator", "memory")

    # We've chosen an interesting case: in_memory_generator does not by default provide its own names
    # so we can still get some names if there is no ambiguity about the namespace
    assert data_context.normalize_data_asset_name("f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    # However, if we add a data_asset that would cause that name to be ambiguous, it will then fail:
    suite = data_context.create_expectation_suite("my_datasource/in_memory_generator/f1", "default")
    data_context.save_expectation_suite(suite)

    with pytest.raises(DataContextError) as exc:
        name = data_context.normalize_data_asset_name("f1")
    assert "Ambiguous data_asset_name 'f1'. Multiple candidates found" in exc.value.message

    # It will also fail with two components since there is still ambiguity:
    with pytest.raises(DataContextError) as exc:
        data_context.normalize_data_asset_name("my_datasource/f1")
    assert "Ambiguous data_asset_name 'my_datasource/f1'. Multiple candidates found" in exc.value.message

    # But we can get the asset using all three components
    assert data_context.normalize_data_asset_name("my_datasource/default/f1") == \
        DataAssetIdentifier("my_datasource", "default", "f1")

    assert data_context.normalize_data_asset_name("my_datasource/in_memory_generator/f1") == \
        DataAssetIdentifier("my_datasource", "in_memory_generator", "f1")


def test_list_datasources(data_context):
    datasources = data_context.list_datasources()

    assert OrderedDict(datasources) == OrderedDict([

        {
            'name': 'mydatasource',
            'class_name': 'PandasDatasource'
        }
    ])

    data_context.add_datasource("second_pandas_source",
                           module_name="great_expectations.datasource",
                           class_name="PandasDatasource",
                           )

    datasources = data_context.list_datasources()

    assert OrderedDict(datasources) == OrderedDict([
        {
            'name': 'mydatasource',
            'class_name': 'PandasDatasource'
        },
        {
            'name': 'second_pandas_source',
            'class_name': 'PandasDatasource'
        }
    ])


def test_data_context_result_store(titanic_data_context):
    """
    Test that validation results can be correctly fetched from the configured results store
    """
    profiling_results = titanic_data_context.profile_datasource("mydatasource")

    for profiling_result in profiling_results['results']:
        data_asset_name = profiling_result[0].data_asset_name
        validation_result = titanic_data_context.get_validation_result(data_asset_name, "BasicDatasetProfiler")
        assert data_asset_name == dataAssetIdentifierSchema.load(validation_result.meta["data_asset_name"]).data

    all_validation_result = titanic_data_context.get_validation_result(
        "mydatasource/mygenerator/Titanic",
        "BasicDatasetProfiler",
    )
    assert len(all_validation_result.results) == 51

    failed_validation_result = titanic_data_context.get_validation_result(
        "mydatasource/mygenerator/Titanic",
        "BasicDatasetProfiler",
        failed_only=True,
    )
    assert len(failed_validation_result.results) == 8


@pytest.mark.rendered_output
def test_render_full_static_site_from_empty_project(tmp_path_factory, filesystem_csv_3):

    # TODO : Use a standard test fixture
    # TODO : Have that test fixture copy a directory, rather than building a new one from scratch

    base_dir = str(tmp_path_factory.mktemp("project_dir"))
    project_dir = os.path.join(base_dir, "project_path")
    os.mkdir(project_dir)

    os.makedirs(os.path.join(project_dir, "data"))
    os.makedirs(os.path.join(project_dir, "data/titanic"))
    shutil.copy(
        "./tests/test_sets/Titanic.csv",
        str(os.path.join(project_dir, "data/titanic/Titanic.csv"))
    )

    os.makedirs(os.path.join(project_dir, "data/random"))
    shutil.copy(
        os.path.join(filesystem_csv_3, "f1.csv"),
        str(os.path.join(project_dir, "data/random/f1.csv"))
    )
    shutil.copy(
        os.path.join(filesystem_csv_3, "f2.csv"),
        str(os.path.join(project_dir, "data/random/f2.csv"))
    )

    assert gen_directory_tree_str(project_dir) == """\
project_path/
    data/
        random/
            f1.csv
            f2.csv
        titanic/
            Titanic.csv
"""

    context = DataContext.create(project_dir)
    ge_directory = os.path.join(project_dir, "great_expectations")
    context.add_datasource("titanic",
                           module_name="great_expectations.datasource",
                           class_name="PandasDatasource",
                           base_directory=os.path.join(project_dir, "data/titanic/"))

    context.add_datasource("random",
                           module_name="great_expectations.datasource",
                           class_name="PandasDatasource",
                           base_directory=os.path.join(project_dir, "data/random/"))

    context.profile_datasource("titanic")

    tree_str = gen_directory_tree_str(project_dir)
    print(tree_str)
    assert tree_str == """\
project_path/
    data/
        random/
            f1.csv
            f2.csv
        titanic/
            Titanic.csv
    great_expectations/
        .gitignore
        great_expectations.yml
        datasources/
        expectations/
            titanic/
                default/
                    Titanic/
                        BasicDatasetProfiler.json
        notebooks/
            pandas/
                create_expectations.ipynb
                validation_playground.ipynb
            spark/
                create_expectations.ipynb
                validation_playground.ipynb
            sql/
                create_expectations.ipynb
                validation_playground.ipynb
        plugins/
            custom_data_docs/
                renderers/
                styles/
                    data_docs_custom_styles.css
                views/
        uncommitted/
            config_variables.yml
            data_docs/
            samples/
            validations/
                profiling/
                    titanic/
                        default/
                            Titanic/
                                BasicDatasetProfiler.json
"""

    context.profile_datasource("random")
    context.build_data_docs()

    data_docs_dir = os.path.join(project_dir, "great_expectations/uncommitted/data_docs")
    observed = gen_directory_tree_str(data_docs_dir)
    print(observed)
    assert observed == """\
data_docs/
    local_site/
        index.html
        expectations/
            random/
                default/
                    f1/
                        BasicDatasetProfiler.html
                    f2/
                        BasicDatasetProfiler.html
            titanic/
                default/
                    Titanic/
                        BasicDatasetProfiler.html
        validations/
            profiling/
                random/
                    default/
                        f1/
                            BasicDatasetProfiler.html
                        f2/
                            BasicDatasetProfiler.html
                titanic/
                    default/
                        Titanic/
                            BasicDatasetProfiler.html
"""

    # save data_docs locally
    safe_mmkdir("./tests/data_context/output")
    safe_mmkdir("./tests/data_context/output/data_docs")

    if os.path.isdir("./tests/data_context/output/data_docs"):
        shutil.rmtree("./tests/data_context/output/data_docs")
    shutil.copytree(
        os.path.join(
            ge_directory,
            "uncommitted/data_docs/"
        ),
        "./tests/data_context/output/data_docs"
    )


def test_add_store(empty_data_context):
    assert "my_new_store" not in empty_data_context.stores.keys()
    assert "my_new_store" not in empty_data_context.get_config()["stores"]
    new_store = empty_data_context.add_store(
        "my_new_store",
        {
            "module_name": "great_expectations.data_context.store",
            "class_name": "ExpectationsStore",
        }
    )
    assert "my_new_store" in empty_data_context.stores.keys()
    assert "my_new_store" in empty_data_context.get_config()["stores"]

    assert isinstance(new_store, ExpectationsStore)


@pytest.fixture
def basic_data_context_config():
    return DataContextConfig(**{
        "commented_map": {},
        "config_version": 1,
        "plugins_directory": "plugins/",
        "config_variables_file_path": None,
        "evaluation_parameter_store_name": "evaluation_parameter_store",
        "validations_store_name": "does_not_have_to_be_real",
        "expectations_store_name": "expectations_store",
        "config_variables_file_path": "uncommitted/config_variables.yml",
        "datasources": {},
        "stores": {
            "expectations_store": {
                "class_name": "ExpectationsStore",
                "store_backend": {
                    "class_name": "FixedLengthTupleFilesystemStoreBackend",
                    "base_directory": "expectations/",
                },
            },
            "evaluation_parameter_store" : {
                "module_name": "great_expectations.data_context.store",
                "class_name": "EvaluationParameterStore",
            }
        },
        "data_docs_sites": {},
        "validation_operators": {
            "default": {
                "class_name": "ActionListValidationOperator",
                "action_list": []
            }
        }
    })


def test_ExplorerDataContext(titanic_data_context):
    context_root_directory = titanic_data_context.root_directory
    explorer_data_context = ExplorerDataContext(context_root_directory)
    assert explorer_data_context._expectation_explorer_manager


def test_ConfigOnlyDataContext__initialization(tmp_path_factory, basic_data_context_config):
    config_path = str(tmp_path_factory.mktemp('test_ConfigOnlyDataContext__initialization__dir'))
    context = ConfigOnlyDataContext(
        basic_data_context_config,
        config_path,
    )

    assert context.root_directory.split("/")[-1] == "test_ConfigOnlyDataContext__initialization__dir0"
    assert context.plugins_directory.split("/")[-3:] == ["test_ConfigOnlyDataContext__initialization__dir0", "plugins",""]


def test__normalize_absolute_or_relative_path(tmp_path_factory, basic_data_context_config):
    config_path = str(tmp_path_factory.mktemp('test__normalize_absolute_or_relative_path__dir'))
    context = ConfigOnlyDataContext(
        basic_data_context_config,
        config_path,
    )

    print(context._normalize_absolute_or_relative_path("yikes"))
    assert "test__normalize_absolute_or_relative_path__dir0/yikes" in context._normalize_absolute_or_relative_path("yikes")

    context._normalize_absolute_or_relative_path("/yikes")
    assert "test__normalize_absolute_or_relative_path__dir" not in context._normalize_absolute_or_relative_path("/yikes")
    assert "/yikes" == context._normalize_absolute_or_relative_path("/yikes")


def test_load_data_context_from_environment_variables(tmp_path_factory):
    try:
        project_path = str(tmp_path_factory.mktemp('data_context'))
        context_path = os.path.join(project_path, "great_expectations")
        safe_mmkdir(context_path)
        shutil.copy("./tests/test_fixtures/great_expectations_basic.yml",
                    str(os.path.join(context_path, "great_expectations.yml")))
        with pytest.raises(DataContextError) as err:
            DataContext.find_context_root_dir()
            assert "Unable to locate context root directory." in err

        os.environ["GE_HOME"] = context_path
        assert DataContext.find_context_root_dir() == context_path
    except Exception:
        raise
    finally:
        # Make sure we unset the environment variable we're using
        del os.environ["GE_HOME"]


def test_data_context_updates_expectation_suite_names(data_context):
    # A data context should update the data_asset_name and expectation_suite_name of expectation suites
    # that it creates when it saves them.

    expectation_suites = data_context.list_expectation_suite_keys()

    # We should have a single expectation suite defined
    assert len(expectation_suites) == 1

    data_asset_name = expectation_suites[0].data_asset_name
    expectation_suite_name = expectation_suites[0].expectation_suite_name

    # We'll get that expectation suite and then update its name and re-save, then verify that everything
    # has been properly updated
    expectation_suite = data_context.get_expectation_suite(
        data_asset_name=data_asset_name,
        expectation_suite_name=expectation_suite_name
    )

    # Note we codify here the current behavior of having a string data_asset_name though typed ExpectationSuite objects
    # will enable changing that
    assert expectation_suite.data_asset_name == data_asset_name
    assert expectation_suite.expectation_suite_name == expectation_suite_name

    # We will now change the data_asset_name and then save the suite in three ways:
    #   1. Directly using the new name,
    #   2. Using a different name that should be overwritten
    #   3. Using the new name but having the context draw that from the suite

    # Finally, we will try to save without a name (deleting it first) to demonstrate that saving will fail.
    expectation_suite.data_asset_name = str(DataAssetIdentifier(
        data_asset_name.datasource,
        data_asset_name.generator,
        "a_new_data_asset"
    ))
    expectation_suite.expectation_suite_name = 'a_new_suite_name'

    data_context.save_expectation_suite(
        expectation_suite=expectation_suite,
        data_asset_name=DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_new_data_asset"
        ),
        expectation_suite_name='a_new_suite_name'
    )

    fetched_expectation_suite = data_context.get_expectation_suite(
        data_asset_name=DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_new_data_asset"
        ),
        expectation_suite_name='a_new_suite_name'
    )

    assert fetched_expectation_suite.data_asset_name == DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_new_data_asset"
        )

    assert fetched_expectation_suite.expectation_suite_name == 'a_new_suite_name'

    #   2. Using a different name that should be overwritten
    data_context.save_expectation_suite(
        expectation_suite=expectation_suite,
        data_asset_name=DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_new_new_data_asset"
        ),
        expectation_suite_name='a_new_new_suite_name'
    )

    fetched_expectation_suite = data_context.get_expectation_suite(
        data_asset_name=DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_new_new_data_asset"
        ),
        expectation_suite_name='a_new_new_suite_name'
    )

    assert fetched_expectation_suite.data_asset_name == DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_new_new_data_asset"
        )

    assert fetched_expectation_suite.expectation_suite_name == 'a_new_new_suite_name'

    # Check that the saved name difference is actually persisted on disk
    with open(os.path.join(
                data_context.root_directory,
                "expectations",
                data_asset_name.datasource,
                data_asset_name.generator,
                "a_new_new_data_asset",
                "a_new_new_suite_name.json"
                ), 'r') as suite_file:
        loaded_suite = namespaceAwareExpectationSuiteSchema.load(json.load(suite_file)).data
        assert loaded_suite.data_asset_name == DataAssetIdentifier(
                data_asset_name.datasource,
                data_asset_name.generator,
                "a_new_new_data_asset"
            )

        assert loaded_suite.expectation_suite_name == 'a_new_new_suite_name'

    #   3. Using the new name but having the context draw that from the suite
    expectation_suite.data_asset_name = DataAssetIdentifier(
        data_asset_name.datasource,
        data_asset_name.generator,
        "a_third_name"
    )
    expectation_suite.expectation_suite_name = "a_third_suite_name"
    data_context.save_expectation_suite(
        expectation_suite=expectation_suite
    )

    fetched_expectation_suite = data_context.get_expectation_suite(
        data_asset_name=DataAssetIdentifier(
            data_asset_name.datasource,
            data_asset_name.generator,
            "a_third_name"
        ),
        expectation_suite_name="a_third_suite_name"
    )
    assert fetched_expectation_suite.data_asset_name == DataAssetIdentifier(
        data_asset_name.datasource,
        data_asset_name.generator,
        "a_third_name"
    )
    assert fetched_expectation_suite.expectation_suite_name == "a_third_suite_name"


def test_data_context_create_does_not_raise_error_or_warning_if_ge_dir_exists(tmp_path_factory):
    project_path = str(tmp_path_factory.mktemp('data_context'))
    DataContext.create(project_path)


def test_data_context_create_raises_warning_and_leaves_existing_yml_untouched(tmp_path_factory):
    project_path = str(tmp_path_factory.mktemp('data_context'))
    DataContext.create(project_path)
    ge_yml = os.path.join(
        project_path,
        "great_expectations/great_expectations.yml"
    )
    with open(ge_yml, "a") as ff:
        ff.write("# LOOK I WAS MODIFIED")

    with pytest.warns(UserWarning):
        DataContext.create(project_path)

    with open(ge_yml, "r") as ff:
        obs = ff.read()
    assert "# LOOK I WAS MODIFIED" in obs


def test_data_context_create_makes_uncommitted_dirs_when_all_are_missing(tmp_path_factory):
    project_path = str(tmp_path_factory.mktemp('data_context'))
    DataContext.create(project_path)

    # mangle the existing setup
    ge_dir = os.path.join(project_path, "great_expectations")
    uncommitted_dir = os.path.join(ge_dir, "uncommitted")
    shutil.rmtree(uncommitted_dir)

    # re-run create to simulate onboarding
    DataContext.create(project_path)
    obs = gen_directory_tree_str(ge_dir)
    print(obs)

    assert os.path.isdir(uncommitted_dir), "No uncommitted directory created"
    assert obs == """\
great_expectations/
    .gitignore
    great_expectations.yml
    datasources/
    expectations/
    notebooks/
        pandas/
            create_expectations.ipynb
            validation_playground.ipynb
        spark/
            create_expectations.ipynb
            validation_playground.ipynb
        sql/
            create_expectations.ipynb
            validation_playground.ipynb
    plugins/
        custom_data_docs/
            renderers/
            styles/
                data_docs_custom_styles.css
            views/
    uncommitted/
        config_variables.yml
        data_docs/
        samples/
        validations/
"""


def test_data_context_create_does_nothing_if_all_uncommitted_dirs_exist(tmp_path_factory):
    expected = """\
great_expectations/
    .gitignore
    great_expectations.yml
    datasources/
    expectations/
    notebooks/
        pandas/
            create_expectations.ipynb
            validation_playground.ipynb
        spark/
            create_expectations.ipynb
            validation_playground.ipynb
        sql/
            create_expectations.ipynb
            validation_playground.ipynb
    plugins/
        custom_data_docs/
            renderers/
            styles/
                data_docs_custom_styles.css
            views/
    uncommitted/
        config_variables.yml
        data_docs/
        samples/
        validations/
"""
    project_path = str(tmp_path_factory.mktemp('stuff'))
    ge_dir = os.path.join(project_path, "great_expectations")

    DataContext.create(project_path)
    fixture = gen_directory_tree_str(ge_dir)
    print(fixture)

    assert fixture == expected

    # re-run create to simulate onboarding
    DataContext.create(project_path)

    obs = gen_directory_tree_str(ge_dir)
    assert obs == expected


def test_data_context_do_all_uncommitted_dirs_exist(tmp_path_factory):
    expected = """\
uncommitted/
    config_variables.yml
    data_docs/
    samples/
    validations/
"""
    project_path = str(tmp_path_factory.mktemp('stuff'))
    ge_dir = os.path.join(project_path, "great_expectations")
    uncommitted_dir = os.path.join(ge_dir, "uncommitted")
    DataContext.create(project_path)
    fixture = gen_directory_tree_str(uncommitted_dir)
    assert fixture == expected

    # Test that all exist
    assert DataContext.all_uncommitted_directories_exist(ge_dir)

    # remove a few
    shutil.rmtree(os.path.join(uncommitted_dir, "data_docs"))
    shutil.rmtree(os.path.join(uncommitted_dir, "validations"))

    # Test that not all exist
    assert not DataContext.all_uncommitted_directories_exist(project_path)


def test_data_context_create_does_not_overwrite_existing_config_variables_yml(tmp_path_factory):
    project_path = str(tmp_path_factory.mktemp('data_context'))
    DataContext.create(project_path)
    ge_dir = os.path.join(project_path, "great_expectations")
    uncommitted_dir = os.path.join(ge_dir, "uncommitted")
    config_vars_yml = os.path.join(uncommitted_dir, "config_variables.yml")

    # modify config variables
    with open(config_vars_yml, "a") as ff:
        ff.write("# LOOK I WAS MODIFIED")

    # re-run create to simulate onboarding
    with pytest.warns(UserWarning):
        DataContext.create(project_path)

    with open(config_vars_yml, "r") as ff:
        obs = ff.read()
    print(obs)
    assert "# LOOK I WAS MODIFIED" in obs


def test_scaffold_directories_and_notebooks(tmp_path_factory):
    empty_directory = str(tmp_path_factory.mktemp("test_scaffold_directories_and_notebooks"))
    DataContext.scaffold_directories(empty_directory)
    DataContext.scaffold_notebooks(empty_directory)

    assert set(os.listdir(empty_directory)) == {
        'datasources',
        'plugins',
        'expectations',
        '.gitignore',
        'uncommitted',
        'notebooks'
    }
    assert set(os.listdir(os.path.join(empty_directory, "uncommitted"))) == {
        'samples',
        'data_docs',
        'validations'
    }
    for subdir in DataContext.NOTEBOOK_SUBDIRECTORIES:
        subdir_path = os.path.join(empty_directory, "notebooks", subdir)
        assert set(os.listdir(subdir_path)) == {
            "create_expectations.ipynb",
            "validation_playground.ipynb"
        }


def test_build_batch_kwargs(titanic_multibatch_data_context):
    data_asset_name = titanic_multibatch_data_context.normalize_data_asset_name("titanic")
    batch_kwargs = titanic_multibatch_data_context.build_batch_kwargs(data_asset_name, "Titanic_1911")
    assert os.path.relpath("./data/titanic/Titanic_1911.csv") in batch_kwargs["path"]
    assert "partition_id" in batch_kwargs
    assert batch_kwargs["partition_id"] == "Titanic_1911"


def test_existing_local_data_docs_urls_returns_nothing_on_empty_project(tmp_path_factory):
    empty_directory = str(tmp_path_factory.mktemp("hey_there"))
    DataContext.create(empty_directory)
    context = DataContext(os.path.join(empty_directory, DataContext.GE_DIR))

    obs = context.get_existing_local_data_docs_sites_urls()
    assert obs == []


def test_existing_local_data_docs_urls_returns_single_url_from_customized_local_site(tmp_path_factory):
    empty_directory = str(tmp_path_factory.mktemp("yo_yo"))
    DataContext.create(empty_directory)
    ge_dir = os.path.join(empty_directory, DataContext.GE_DIR)
    context = DataContext(ge_dir)

    context._project_config["data_docs_sites"] = {
        "my_rad_site": {
            "class_name": "SiteBuilder",
            "store_backend": {
                "class_name": "FixedLengthTupleFilesystemStoreBackend",
                "base_directory": "uncommitted/data_docs/some/local/path/"
            }
        }
    }

    # TODO Workaround project config programmatic config manipulation
    #  statefulness issues by writing to disk and re-upping a new context
    context._save_project_config()
    context = DataContext(ge_dir)
    context.build_data_docs()

    expected_path = os.path.join(ge_dir, "uncommitted/data_docs/some/local/path/index.html")
    assert os.path.isfile(expected_path)

    obs = context.get_existing_local_data_docs_sites_urls()
    assert obs == ["file://{}".format(expected_path)]


def test_existing_local_data_docs_urls_returns_multiple_urls_from_customized_local_site(tmp_path_factory):
    empty_directory = str(tmp_path_factory.mktemp("yo_yo_ma"))
    DataContext.create(empty_directory)
    ge_dir = os.path.join(empty_directory, DataContext.GE_DIR)
    context = DataContext(ge_dir)

    context._project_config["data_docs_sites"] = {
        "my_rad_site": {
            "class_name": "SiteBuilder",
            "store_backend": {
                "class_name": "FixedLengthTupleFilesystemStoreBackend",
                "base_directory": "uncommitted/data_docs/some/path/"
            }
        },
        "another_just_amazing_site": {
            "class_name": "SiteBuilder",
            "store_backend": {
                "class_name": "FixedLengthTupleFilesystemStoreBackend",
                "base_directory": "uncommitted/data_docs/another/path/"
            }
        }
    }

    # TODO Workaround project config programmatic config manipulation
    #  statefulness issues by writing to disk and re-upping a new context
    context._save_project_config()
    context = DataContext(ge_dir)
    context.build_data_docs()
    data_docs_dir = os.path.join(ge_dir, "uncommitted/data_docs/")

    path_1 = os.path.join(data_docs_dir, "some/path/index.html")
    path_2 = os.path.join(data_docs_dir, "another/path/index.html")
    for expected_path in [path_1, path_2]:
        assert os.path.isfile(expected_path)

    obs = context.get_existing_local_data_docs_sites_urls()
    assert set(obs) == set([
        "file://{}".format(path_1),
        "file://{}".format(path_2),
    ])


def test_existing_local_data_docs_urls_returns_only_existing_urls_from_customized_local_site(tmp_path_factory):
    """
    This test ensures that the method only returns known-good urls where the
    index.html file actually exists.
    """
    empty_directory = str(tmp_path_factory.mktemp("yo_yo_ma"))
    DataContext.create(empty_directory)
    ge_dir = os.path.join(empty_directory, DataContext.GE_DIR)
    context = DataContext(ge_dir)

    context._project_config["data_docs_sites"] = {
        "my_rad_site": {
            "class_name": "SiteBuilder",
            "store_backend": {
                "class_name": "FixedLengthTupleFilesystemStoreBackend",
                "base_directory": "uncommitted/data_docs/some/path/"
            }
        },
        "another_just_amazing_site": {
            "class_name": "SiteBuilder",
            "store_backend": {
                "class_name": "FixedLengthTupleFilesystemStoreBackend",
                "base_directory": "uncommitted/data_docs/another/path/"
            }
        }
    }

    # TODO Workaround project config programmatic config manipulation
    #  statefulness issues by writing to disk and re-upping a new context
    context._save_project_config()
    context = DataContext(ge_dir)
    context.build_data_docs()
    data_docs_dir = os.path.join(ge_dir, "uncommitted/data_docs/")

    # Mangle one of the local sites
    shutil.rmtree(os.path.join(data_docs_dir, "some/"))
    path_1 = os.path.join(data_docs_dir, "some/path/index.html")
    assert not os.path.isfile(path_1)
    path_2 = os.path.join(data_docs_dir, "another/path/index.html")
    assert os.path.isfile(path_2)

    obs = context.get_existing_local_data_docs_sites_urls()
    assert obs == [
        "file://{}".format(path_2),
    ]

def test_load_config_variables_file(basic_data_context_config, tmp_path_factory):
    # Setup:
    base_path = str(tmp_path_factory.mktemp('test_load_config_variables_file'))
    safe_mmkdir(os.path.join(base_path, "uncommitted"))
    with open(os.path.join(base_path, "uncommitted", "dev_variables.yml"), "w") as outfile:
        yaml.dump({'env': 'dev'}, outfile)
    with open(os.path.join(base_path, "uncommitted", "prod_variables.yml"), "w") as outfile:
        yaml.dump({'env': 'prod'}, outfile)
    basic_data_context_config["config_variables_file_path"] = "uncommitted/${TEST_CONFIG_FILE_ENV}_variables.yml"
    context = ConfigOnlyDataContext(basic_data_context_config, context_root_dir=base_path)

    try:
        # We should be able to load different files based on an environment variable
        os.environ["TEST_CONFIG_FILE_ENV"] = "dev"
        vars = context._load_config_variables_file()
        assert vars['env'] == 'dev'
        os.environ["TEST_CONFIG_FILE_ENV"] = "prod"
        vars = context._load_config_variables_file()
        assert vars['env'] == 'prod'
    except Exception:
        raise
    finally:
        # Make sure we unset the environment variable we're using
        del os.environ["TEST_CONFIG_FILE_ENV"]
