"""Class to perform under-sampling based on the condensed nearest neighbour
method."""
# Adapted from imbalanced-learn

# Authors: Guillaume Lemaitre <g.lemaitre58@gmail.com>
#          Christos Aridas
#          Zhining Liu <zhining.liu@outlook.com>
# License: MIT

# %%
LOCAL_DEBUG = False

if not LOCAL_DEBUG:
    from ..base import BaseCleaningSampler
    from ....utils._docstring import _n_jobs_docstring, Substitution
    from ....utils._docstring import _random_state_docstring
    from ....utils._validation import _deprecate_positional_args
else:
    # For local test
    import sys
    sys.path.append("../../..")
    from sampler.under_sampling.base import BaseCleaningSampler
    from utils._docstring import _n_jobs_docstring, Substitution
    from utils._docstring import _random_state_docstring
    from utils._validation import _deprecate_positional_args

import numpy as np
from scipy.sparse import issparse
from collections import Counter

from sklearn.base import clone
from sklearn.neighbors import KNeighborsClassifier
from sklearn.utils import check_random_state, _safe_indexing


@Substitution(
    sampling_strategy=BaseCleaningSampler._sampling_strategy_docstring,
    n_jobs=_n_jobs_docstring,
    random_state=_random_state_docstring,
)
class CondensedNearestNeighbour(BaseCleaningSampler):
    """Undersample based on the condensed nearest neighbour method.

    Read more in the `User Guide <https://imbalanced-learn.org/stable/under_sampling.html#condensed-nearest-neighbors>`_.

    Parameters
    ----------
    {sampling_strategy}

    {random_state}

    n_neighbors : int or estimator object, default=None
        If ``int``, size of the neighbourhood to consider to compute the
        nearest neighbors. If object, an estimator that inherits from
        :class:`~sklearn.neighbors.base.KNeighborsMixin` that will be used to
        find the nearest-neighbors.  If `None`, a
        :class:`~sklearn.neighbors.KNeighborsClassifier` with a 1-NN rules will
        be used.

    n_seeds_S : int, default=1
        Number of samples to extract in order to build the set S.

    {n_jobs}

    Attributes
    ----------
    sample_indices_ : ndarray of shape (n_new_samples,)
        Indices of the samples selected.

    See Also
    --------
    EditedNearestNeighbours : Undersample by editing samples.

    RepeatedEditedNearestNeighbours : Undersample by repeating ENN algorithm.

    AllKNN : Undersample using ENN and various number of neighbours.

    Notes
    -----
    The method is based on [1]_.

    Supports multi-class resampling. A one-vs.-rest scheme is used when
    sampling a class as proposed in [1]_.

    References
    ----------
    .. [1] P. Hart, "The condensed nearest neighbor rule,"
       In Information Theory, IEEE Transactions on, vol. 14(3),
       pp. 515-516, 1968.

    Examples
    --------
    >>> from collections import Counter # doctest: +SKIP
    >>> from sklearn.datasets import fetch_mldata # doctest: +SKIP
    >>> from imbalanced_ensemble.sampler.under_sampling import \
CondensedNearestNeighbour # doctest: +SKIP
    >>> pima = fetch_mldata('diabetes_scale') # doctest: +SKIP
    >>> X, y = pima['data'], pima['target'] # doctest: +SKIP
    >>> print('Original dataset shape %s' % Counter(y)) # doctest: +SKIP
    Original dataset shape Counter({{1: 500, -1: 268}}) # doctest: +SKIP
    >>> cnn = CondensedNearestNeighbour(random_state=42) # doctest: +SKIP
    >>> X_res, y_res = cnn.fit_resample(X, y) #doctest: +SKIP
    >>> print('Resampled dataset shape %s' % Counter(y_res)) # doctest: +SKIP
    Resampled dataset shape Counter({{-1: 268, 1: 227}}) # doctest: +SKIP
    """

    @_deprecate_positional_args
    def __init__(
        self,
        *,
        sampling_strategy="auto",
        random_state=None,
        n_neighbors=None,
        n_seeds_S=1,
        n_jobs=None,
    ):
        super().__init__(sampling_strategy=sampling_strategy)
        self.random_state = random_state
        self.n_neighbors = n_neighbors
        self.n_seeds_S = n_seeds_S
        self.n_jobs = n_jobs

    def _validate_estimator(self):
        """Private function to create the NN estimator"""
        if self.n_neighbors is None:
            self.estimator_ = KNeighborsClassifier(n_neighbors=1, n_jobs=self.n_jobs)
        elif isinstance(self.n_neighbors, int):
            self.estimator_ = KNeighborsClassifier(
                n_neighbors=self.n_neighbors, n_jobs=self.n_jobs
            )
        elif isinstance(self.n_neighbors, KNeighborsClassifier):
            self.estimator_ = clone(self.n_neighbors)
        else:
            raise ValueError(
                f"`n_neighbors` has to be a int or an object"
                f" inhereited from KNeighborsClassifier."
                f" Got {type(self.n_neighbors)} instead."
            )

    def _fit_resample(self, X, y, sample_weight=None):
        self._validate_estimator()

        random_state = check_random_state(self.random_state)
        target_stats = Counter(y)
        class_minority = min(target_stats, key=target_stats.get)
        idx_under = np.empty((0,), dtype=int)

        for target_class in np.unique(y):
            if target_class in self.sampling_strategy_.keys():
                # Randomly get one sample from the majority class
                # Generate the index to select
                idx_maj = np.flatnonzero(y == target_class)
                idx_maj_sample = idx_maj[
                    random_state.randint(
                        low=0,
                        high=target_stats[target_class],
                        size=self.n_seeds_S,
                    )
                ]

                # Create the set C - One majority samples and all minority
                C_indices = np.append(
                    np.flatnonzero(y == class_minority), idx_maj_sample
                )
                C_x = _safe_indexing(X, C_indices)
                C_y = _safe_indexing(y, C_indices)

                # Create the set S - all majority samples
                S_indices = np.flatnonzero(y == target_class)
                S_x = _safe_indexing(X, S_indices)
                S_y = _safe_indexing(y, S_indices)

                # fit knn on C
                self.estimator_.fit(C_x, C_y)

                good_classif_label = idx_maj_sample.copy()
                # Check each sample in S if we keep it or drop it
                for idx_sam, (x_sam, y_sam) in enumerate(zip(S_x, S_y)):

                    # Do not select sample which are already well classified
                    if idx_sam in good_classif_label:
                        continue

                    # Classify on S
                    if not issparse(x_sam):
                        x_sam = x_sam.reshape(1, -1)
                    pred_y = self.estimator_.predict(x_sam)

                    # If the prediction do not agree with the true label
                    # append it in C_x
                    if y_sam != pred_y:
                        # Keep the index for later
                        idx_maj_sample = np.append(idx_maj_sample, idx_maj[idx_sam])

                        # Update C
                        C_indices = np.append(C_indices, idx_maj[idx_sam])
                        C_x = _safe_indexing(X, C_indices)
                        C_y = _safe_indexing(y, C_indices)

                        # fit a knn on C
                        self.estimator_.fit(C_x, C_y)

                        # This experimental to speed up the search
                        # Classify all the element in S and avoid to test the
                        # well classified elements
                        pred_S_y = self.estimator_.predict(S_x)
                        good_classif_label = np.unique(
                            np.append(idx_maj_sample, np.flatnonzero(pred_S_y == S_y))
                        )

                idx_under = np.concatenate((idx_under, idx_maj_sample), axis=0)
            else:
                idx_under = np.concatenate(
                    (idx_under, np.flatnonzero(y == target_class)), axis=0
                )

        self.sample_indices_ = idx_under

        if sample_weight is not None:
            # sample_weight is already validated in self.fit_resample()
            sample_weight_under = _safe_indexing(sample_weight, idx_under)
            return _safe_indexing(X, idx_under), _safe_indexing(y, idx_under), sample_weight_under
        else: return _safe_indexing(X, idx_under), _safe_indexing(y, idx_under)


    def _more_tags(self):
        return {"sample_indices": True}

# # %%

# if __name__ == "__main__":
#     from collections import Counter
#     from sklearn.datasets import make_classification
#     X, y = make_classification(n_classes=3, class_sep=2,
#         weights=[0.1, 0.3, 0.6], n_informative=3, n_redundant=1, flip_y=0,
#         n_features=20, n_clusters_per_class=1, n_samples=1000, random_state=10)
#     print('Original dataset shape %s' % Counter(y))

#     origin_distr = Counter(y)
#     target_distr = [1, 2]
#     target_distr = {2: 200, 1: 100, 0: 100}

#     undersampler = CondensedNearestNeighbour(random_state=42, sampling_strategy=target_distr)
#     X_res, y_res, weight_res = undersampler.fit_resample(X, y, sample_weight=y)

#     print('Resampled dataset shape %s' % Counter(y_res))
#     print('Test resampled weight shape %s' % Counter(weight_res))

# # %%
