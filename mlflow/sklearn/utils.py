import inspect
import logging
import mlflow
import sklearn

from distutils.version import LooseVersion
from itertools import islice
from mlflow.utils.autologging_utils import try_mlflow_log

_logger = logging.getLogger(__name__)

# The earliest version we're guaranteed to support. Autologging utilities may not work properly
# on scikit-learn older than this version.
_MIN_SKLEARN_VERSION = "0.20.3"

_NORMALIZE = "normalize"
_SAMPLE_WEIGHT = "sample_weight"

client = mlflow.tracking.MlflowClient()


def _get_Xy(args, kwargs, X_var_name, y_var_name):
    # corresponds to: model.fit(X, y)
    if len(args) >= 2:
        return args[:2]

    # corresponds to: model.fit(X, <y_var_name>=y)
    if len(args) == 1:
        return args[0], kwargs[y_var_name]

    # corresponds to: model.fit(<X_var_name>=X, <y_var_name>=y)
    return kwargs[X_var_name], kwargs[y_var_name]


def _get_sample_weight(arg_names, args, kwargs):
    sample_weight_index = arg_names.index(_SAMPLE_WEIGHT)

    # corresponds to: model.fit(X, y, ..., sample_weight)
    if len(args) > sample_weight_index:
        return args[sample_weight_index]

    # corresponds to: model.fit(X, y, ..., sample_weight=sample_weight)
    if _SAMPLE_WEIGHT in kwargs:
        return kwargs[_SAMPLE_WEIGHT]

    return None


def _get_arg_names(f):
    # `inspect.getargspec` doesn't return a wrapped function's argspec
    # See: https://hynek.me/articles/decorators#mangled-signatures
    return list(inspect.signature(f).parameters.keys())


def _get_args_for_score(score_func, fit_func, fit_args, fit_kwargs):
    """
    Get arguments to pass to score_func in the following steps.

    1. Extract X and y from fit_args and fit_kwargs.
    2. If the sample_weight argument exists in both score_func and fit_func,
       extract it from fit_args or fit_kwargs and return (X, y, sample_weight),
       otherwise return (X, y)

    :param score_func: A score function object.
    :param fit_func: A fit function object.
    :param fit_args: Positional arguments given to fit_func.
    :param fit_kwargs: Keyword arguments given to fit_func.

    :returns: A tuple of either (X, y, sample_weight) or (X, y).
    """
    score_arg_names = _get_arg_names(score_func)
    fit_arg_names = _get_arg_names(fit_func)

    # In most cases, X_var_name and y_var_name become "X" and "y", respectively.
    # However, certain sklearn models use different variable names for X and y.
    # See: https://scikit-learn.org/stable/modules/generated/sklearn.covariance.GraphicalLasso.html#sklearn.covariance.GraphicalLasso.score # noqa: E501
    X_var_name, y_var_name = fit_arg_names[:2]
    Xy = _get_Xy(fit_args, fit_kwargs, X_var_name, y_var_name)

    if (_SAMPLE_WEIGHT in fit_arg_names) and (_SAMPLE_WEIGHT in score_arg_names):
        sample_weight = _get_sample_weight(fit_arg_names, fit_args, fit_kwargs)
        return (*Xy, sample_weight)

    return Xy


def _log_classifier_metrics(trained_model, fit_args, fit_kwargs):
    """
    Compute and log various common metrics for classifiers

    For (1) precision score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_score.html#sklearn.metrics.precision_score
    (2) recall score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.recall_score.html#sklearn.metrics.recall_score
    (3) f1_score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.f1_score.html#sklearn.metrics.f1_score
    By default, we choose the parameter `labels` to be `None`, `pos_label` to be `1`, `average` to be `weighted` to
    compute the weighted precision score.

    For accuracy score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.accuracy_score.html
    we choose the parameter `normalize` to be `True` to output the percentage of accuracy
    as opposed to `False` that outputs the absolute correct number of sample prediction

    Steps:
    1. Extract X and y_true from fit_args and fit_kwargs.
    2. If the sample_weight argument exists in fit_func (accuracy_score by default has sample_weight),
       extract it from fit_args or fit_kwargs as (y_true, y_pred, ...... sample_weight),
       otherwise as (y_true, y_pred, ......)
    3. Compute and log the specific metric

    :param trained_model: The already fitted classifier
    :param fit_args: Positional arguments given to fit_func.
    :param fit_kwargs: Keyword arguments given to fit_func.
    :return:
    """
    fit_arg_names = _get_arg_names(trained_model.fit)

    # In most cases, X_var_name and y_var_name become "X" and "y", respectively.
    # However, certain sklearn models use different variable names for X and y.
    X_var_name, y_var_name = fit_arg_names[:2]
    X, y_true = _get_Xy(fit_args, fit_kwargs, X_var_name, y_var_name)
    y_pred = trained_model.predict(X)

    # Maintain 2 metrics dictionary to store metrics info
    # name_obj_metrics_dict stores pairs of <function name, function object>
    # name_args_metrics_dict stores pairs of <function name, function arguments>
    name_obj_metrics_dict = {'precision_score': sklearn.metrics.precision_score,
                             'recall_score': sklearn.metrics.recall_score,
                             'f1_score': sklearn.metrics.f1_score,
                             'accuracy_score': sklearn.metrics.accuracy_score}
    name_args_metrics_dict = {'precision_score': (y_true, y_pred, None, 1, 'weighted'),
                              'recall_score': (y_true, y_pred, None, 1, 'weighted'),
                              'f1_score': (y_true, y_pred, None, 1, 'weighted'),
                              'accuracy_score': (y_true, y_pred, True)}

    for func_name, func_object in name_obj_metrics_dict.items():
        try:
            if _SAMPLE_WEIGHT in fit_arg_names:
                sample_weight = _get_sample_weight(fit_arg_names, fit_args, fit_kwargs)
                func_args = *name_args_metrics_dict[func_name], sample_weight
            else:
                func_args = name_args_metrics_dict[func_name]
            func_score = func_object(*func_args)
        except Exception as e:  # pylint: disable=broad-except
            msg = (
                    func_object.__qualname__
                    + " failed. The " + func_name + " metric will not be recorded. Scoring error: "
                    + str(e)
            )
            _logger.warning(msg)
        else:
            # try_mlflow_log(client.log_metric, mlflow.active_run().info.run_id, func_name, func_score)
            try_mlflow_log(mlflow.log_metric, func_name, func_score)


def _log_regressor_metrics(trained_model, fit_args, fit_kwargs):
    """
    Compute and log various common metrics for regressors

    For (1) (root) mean squared error: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.mean_squared_error.html#sklearn.metrics.mean_squared_error
    (2) mean absolute error: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.mean_absolute_error.html#sklearn.metrics.mean_absolute_error
    (3) r2 score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.r2_score.html#sklearn.metrics.r2_score
    By default, we choose the parameter `multioutput` to be `uniform_average` to average outputs with uniform weight.

    Steps:
    1. Extract X and y_true from fit_args and fit_kwargs.
    2. If the sample_weight argument exists in fit_func (accuracy_score by default has sample_weight),
       extract it from fit_args or fit_kwargs as (y_true, y_pred, sample_weight, multioutput),
       otherwise as (y_true, y_pred, multioutput)
    3. Compute and log the specific metric

    :param trained_model: The already fitted regressor
    :param fit_args: Positional arguments given to fit_func.
    :param fit_kwargs: Keyword arguments given to fit_func.
    :return:
    """

    fit_arg_names = _get_arg_names(trained_model.fit)
    # In most cases, X_var_name and y_var_name become "X" and "y", respectively.
    # However, certain sklearn models use different variable names for X and y.
    X_var_name, y_var_name = fit_arg_names[:2]
    X, y_true = _get_Xy(fit_args, fit_kwargs, X_var_name, y_var_name)
    y_pred = trained_model.predict(X)

    # Maintain 2 metrics dictionary to store metrics info
    # name_obj_metrics_dict stores pairs of <function name, function object>
    # name_args_metrics_dict stores pairs of <function name, function arguments>
    name_obj_metrics_dict = {'mse': sklearn.metrics.mean_squared_error,
                             'rmse': sklearn.metrics.mean_squared_error,
                             'mae': sklearn.metrics.mean_absolute_error,
                             'r2_score': sklearn.metrics.r2_score}
    name_args_metrics_dict = {'mse': (y_true, y_pred),
                              'rmse': (y_true, y_pred),
                              'mae': (y_true, y_pred),
                              'r2_score': (y_true, y_pred)}

    for func_name, func_object in name_obj_metrics_dict.items():
        try:
            if _SAMPLE_WEIGHT in fit_arg_names:
                sample_weight = _get_sample_weight(fit_arg_names, fit_args, fit_kwargs)
                func_args = *name_args_metrics_dict[func_name], sample_weight
            else:
                func_args = name_args_metrics_dict[func_name]
            # Always add the multioutput default value 'uniform_average'
            # A special case for rmse, the last boolean for parameter 'squared' is needed
            func_args = (*func_args, 'uniform_average', False) \
                if (func_name == 'rmse') else (*func_args, 'uniform_average')
            func_score = func_object(*func_args)
        except Exception as e:  # pylint: disable=broad-except
            msg = (
                    func_object.__qualname__
                    + " failed. The " + func_name + " metric will not be recorded. Scoring error: "
                    + str(e)
            )
            _logger.warning(msg)
        else:
            # try_mlflow_log(client.log_metric, mlflow.active_run().info.run_id, func_name, func_score)
            try_mlflow_log(mlflow.log_metric, func_name, func_score)


def log_clusterer_metrics(trained_model, fit_args, fit_kwargs):
    """
    Compute and log various common metrics for clusterers

    For (1) completeness score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.completeness_score.html#sklearn.metrics.completeness_score
    (2) homogeneity score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.homogeneity_score.html#sklearn.metrics.homogeneity_score
    (3) v-measure score: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.v_measure_score.html#sklearn.metrics.v_measure_score
    By default, we choose the parameter 'beta' for v-measure score to be 1.0.

    Steps:
    1. Extract X and y_true from fit_args and fit_kwargs.
    2. Compute and log the specific metric

    :param trained_model: The already fitted clusterer
    :param fit_args: Positional arguments given to fit_func.
    :param fit_kwargs: Keyword arguments given to fit_func.
    :return:
    """
    fit_arg_names = _get_arg_names(trained_model.fit)

    # In most cases, X_var_name and y_var_name become "X" and "y", respectively.
    # However, certain sklearn models use different variable names for X and y.
    X_var_name, y_var_name = fit_arg_names[:2]
    X, y_true = _get_Xy(fit_args, fit_kwargs, X_var_name, y_var_name)
    y_pred = trained_model.predict(X)

    # Maintain 2 metrics dictionary to store metrics info
    # name_obj_metrics_dict stores pairs of <function name, function object>
    # name_args_metrics_dict stores pairs of <function name, function arguments>
    name_obj_metrics_dict = {'completeness_score': sklearn.metrics.completeness_score,
                             'homogeneity_score': sklearn.metrics.homogeneity_score,
                             'v_measure_score': sklearn.metrics.v_measure_score}
    name_args_metrics_dict = {'completeness_score': (y_true, y_pred),
                              'homogeneity_score': (y_true, y_pred),
                              'v_measure_score': (y_true, y_pred, 1.0)}

    for func_name, func_object in name_obj_metrics_dict.items():
        try:
            func_args = name_args_metrics_dict[func_name]
            func_score = func_object(*func_args)
        except Exception as e:  # pylint: disable=broad-except
            msg = (
                    func_object.__qualname__
                    + " failed. The " + func_name + " metric will not be recorded. Scoring error: "
                    + str(e)
            )
            _logger.warning(msg)
        else:
            # try_mlflow_log(client.log_metric, mlflow.active_run().info.run_id, func_name, func_score)
            try_mlflow_log(mlflow.log_metric, func_name, func_score)


def _chunk_dict(d, chunk_size):
    # Copied from: https://stackoverflow.com/a/22878842

    it = iter(d)
    for _ in range(0, len(d), chunk_size):
        yield {k: d[k] for k in islice(it, chunk_size)}


def _truncate_dict(d, max_key_length=None, max_value_length=None):
    key_is_none = max_key_length is None
    val_is_none = max_value_length is None

    if key_is_none and val_is_none:
        raise ValueError("Must specify at least either `max_key_length` or `max_value_length`")

    truncated = {}
    for k, v in d.items():
        should_truncate_key = (not key_is_none) and (len(str(k)) > max_key_length)
        should_truncate_val = (not val_is_none) and (len(str(v)) > max_value_length)

        new_k = str(k)[:max_key_length] if should_truncate_key else k
        if should_truncate_key:
            msg = "Truncated the key `{}`".format(k)
            _logger.warning(msg)

        new_v = str(v)[:max_value_length] if should_truncate_val else v
        if should_truncate_val:
            msg = "Truncated the value `{}` (in the key `{}`)".format(v, k)
            _logger.warning(msg)

        truncated[new_k] = new_v

    return truncated


def _is_supported_version():
    import sklearn

    return LooseVersion(sklearn.__version__) >= LooseVersion(_MIN_SKLEARN_VERSION)


def _all_estimators():
    try:
        from sklearn.utils import all_estimators

        return all_estimators()
    except ImportError:
        return _backported_all_estimators()


def _backported_all_estimators(type_filter=None):
    """
    Backported from scikit-learn 0.23.2:
    https://github.com/scikit-learn/scikit-learn/blob/0.23.2/sklearn/utils/__init__.py#L1146

    Use this backported `all_estimators` in old versions of sklearn because:
    1. An inferior version of `all_estimators` that old versions of sklearn use for testing,
       might function differently from a newer version.
    2. This backported `all_estimators` works on old versions of sklearn that don’t even define
       the testing utility variant of `all_estimators`.

    ========== original docstring ==========

    Get a list of all estimators from sklearn.
    This function crawls the module and gets all classes that inherit
    from BaseEstimator. Classes that are defined in test-modules are not
    included.
    By default meta_estimators such as GridSearchCV are also not included.
    Parameters
    ----------
    type_filter : string, list of string,  or None, default=None
        Which kind of estimators should be returned. If None, no filter is
        applied and all estimators are returned.  Possible values are
        'classifier', 'regressor', 'cluster' and 'transformer' to get
        estimators only of these specific types, or a list of these to
        get the estimators that fit at least one of the types.
    Returns
    -------
    estimators : list of tuples
        List of (name, class), where ``name`` is the class name as string
        and ``class`` is the actuall type of the class.
    """
    # lazy import to avoid circular imports from sklearn.base
    import pkgutil
    import platform
    import sklearn
    from importlib import import_module
    from operator import itemgetter
    from sklearn.utils.testing import ignore_warnings  # pylint: disable=no-name-in-module
    from sklearn.base import (
        BaseEstimator,
        ClassifierMixin,
        RegressorMixin,
        TransformerMixin,
        ClusterMixin,
    )

    IS_PYPY = platform.python_implementation() == "PyPy"

    def is_abstract(c):
        if not (hasattr(c, "__abstractmethods__")):
            return False
        if not len(c.__abstractmethods__):
            return False
        return True

    all_classes = []
    modules_to_ignore = {"tests", "externals", "setup", "conftest"}
    root = sklearn.__path__[0]  # sklearn package
    # Ignore deprecation warnings triggered at import time and from walking
    # packages
    with ignore_warnings(category=FutureWarning):
        for _, modname, _ in pkgutil.walk_packages(path=[root], prefix="sklearn."):
            mod_parts = modname.split(".")
            if any(part in modules_to_ignore for part in mod_parts) or "._" in modname:
                continue
            module = import_module(modname)
            classes = inspect.getmembers(module, inspect.isclass)
            classes = [(name, est_cls) for name, est_cls in classes if not name.startswith("_")]

            # TODO: Remove when FeatureHasher is implemented in PYPY
            # Skips FeatureHasher for PYPY
            if IS_PYPY and "feature_extraction" in modname:
                classes = [(name, est_cls) for name, est_cls in classes if name == "FeatureHasher"]

            all_classes.extend(classes)

    all_classes = set(all_classes)

    estimators = [
        c for c in all_classes if (issubclass(c[1], BaseEstimator) and c[0] != "BaseEstimator")
    ]
    # get rid of abstract base classes
    estimators = [c for c in estimators if not is_abstract(c[1])]

    if type_filter is not None:
        if not isinstance(type_filter, list):
            type_filter = [type_filter]
        else:
            type_filter = list(type_filter)  # copy
        filtered_estimators = []
        filters = {
            "classifier": ClassifierMixin,
            "regressor": RegressorMixin,
            "transformer": TransformerMixin,
            "cluster": ClusterMixin,
        }
        for name, mixin in filters.items():
            if name in type_filter:
                type_filter.remove(name)
                filtered_estimators.extend([est for est in estimators if issubclass(est[1], mixin)])
        estimators = filtered_estimators
        if type_filter:
            raise ValueError(
                "Parameter type_filter must be 'classifier', "
                "'regressor', 'transformer', 'cluster' or "
                "None, got"
                " %s." % repr(type_filter)
            )

    # drop duplicates, sort for reproducibility
    # itemgetter is used to ensure the sort does not extend to the 2nd item of
    # the tuple
    return sorted(set(estimators), key=itemgetter(0))
