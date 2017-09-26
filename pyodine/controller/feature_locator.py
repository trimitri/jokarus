"""Aid in locating a given feature in a reference spectrum.

This module is a wrapper for the contained "FeatureLocator" class.
"""
import logging
from typing import Dict, List, Tuple, Union  # pylint: disable=unused-import

import numpy as np
from scipy import signal, interpolate

LOGGER = logging.getLogger('pyodine.controller.feature_locator')


class FeatureLocator:
    """Find distorted samples' positions inside a reference signal.

    We assume that the supplied reference signal/spectrum etc. has a nontrivial
    shape (a sufficient density of distinguishable features). Presented with a
    sample resembling a part of the reference spectrum, this class may then
    determine the position in the reference at which that sample once belonged.

    It also provides a "confidence" rating, which may be used to determine if
    the sample at hand does belong in the reference at all.
    """
    def __init__(self, feature_threshold: float = 0.001) -> None:
        self.feature_threshold = feature_threshold
        # How much arbitrary units does the reference signal span?
        self._ref = None  # type: np.ndarray
        self.ref_span = None  # type: float
        self._corr = None  # type: np.ndarray
        self._norms = {}  # type: Dict[int, np.ndarray]
        self._ref = None  # type: np.ndarray
        self._sample = None  # type: np.ndarray

    @property
    def reference(self) -> np.ndarray:
        return self._ref

    @reference.setter
    def reference(self, ref: np.ndarray) -> None:
        self._ref = ref

        # Mark quantities that need to be recalculated when a new reference was
        # set.
        self._corr = None
        self._norms = {}

    def correlate(self) -> np.ndarray:
        """The (tweaked) cross correlation between sample and reference.

        This may be used for visual control of match quality.

        :raises RuntimeError: Reference or sample weren't set before using this
                    method.
        """
        if self._ref is None or self._sample is None:
            raise RuntimeError("Set ref and sample before correlating.")

        if self._corr is None:
            self._corr = signal.correlate(self._ref, self._sample, mode='valid')
            self._corr = np.divide(self._corr, self._get_normalization())
        return self._corr

    def locate_sample(self, sample: np.ndarray, span: float) -> List[Tuple[float, float]]:
        """The core functionality. Locate a sample in a reference.

        :param span: The span of the sample in arbitrary units. Those need to
                    be the same units that were used when defining the
                    reference. It must be smaller than the reference span.

        :raises ValueError: `sample` is of wrong shape.
        :raises ValueError: `span` is not in ]0, <ref. span>[.

        :returns: A list of tuples (position, confidence) indicating the most
                    probable locations in the reference from where the sample
                    may have originated. `position` is a float in [0, rs[,
                    indicating the position of the sample's left edge. "rs" is
                    the reference span. `position` will always be smaller than
                    "rs", as the sample itself has a finite width.
                    `confidence` is an *arbitrary* indicator in [0, 1] of how
                    probable it is for the sample to actually have originated
                    from `position`.  For no matches, the list may be empty.
        """
        if sample.shape[0] != 2:
            raise ValueError("Sample has to have (2, n) shape for n sampled points.")
        if not span > 0 or not span < self.ref_span:
            raise ValueError("Sample span needs to be in ]0, <ref. span>[.")

        self._set_sample(sample, span)
        position = self.correlate().argmax() / len(self._ref) * self.ref_span

        # Returns a 1-element tuple of array indices where local maximums are
        # located. Relative max's at the very start and end of the corr. signal
        # are not counted, as they wouldn't give an accurate position.
        maxima_ind = signal.argrelmax(self.correlate(), mode='wrap')[0]
        maxima = [[p, self.correlate()[p]] for p in maxima_ind]
        maxima = maxima[np.argsort(maxima[:, 1])]  # Sort by height of maximum.

        # The probable occurrences were found now. We still need to scale the
        # x-axis to arbitrary (reference) units and provide a meaningful
        # confidence indicator that will replace the bare maximum height.

        if len(maxima) > 1:

            # Compare highest maximum to second highest.
            confidence = (maxima[-1] - maxima[-2]) / maxima[-1]
        elif len(maxima) == 1:
            confidence = 1  # Only one maximum was found.
        else:
            confidence = 0  # No maximum was found.

        # TODO Do what's proclaimed in the docs above: Return multiple
        # candidates.
        return [(position, confidence)]

    def _assign_confidence(self, maxima: List[int, float]) -> List[int, float]:
        """Estimate the reliability of match candidates.

        The cross correlation analysis done in this class will usually yield
        more than one candidate for positions in the reference at which a given
        signal might have originated. As *at most* one of the finds is the
        correct match, we need to provide the user with an estimation of match
        quality, which is what this function tries to give.
        """

        # TODO All of the confidence estimators below lack the important
        # feature of reliably rejecting signals that don't fit at all, e.g.
        # using the absolute value of the correlation function as an indicator.
        # This feature is requested in issue #135.

        weighted = maxima[::-1]  # Put best match first (flip list).
        if len(weighted) == 1:
            # If there's only one local maximum found, we'll judge the
            # situation by comparing the maximum value to the arithmetic mean
            # of the overall correlation signal. When using a complex
            # reference signal, this situation should not usually occur. It is
            # mainly here to avoid false positives in such cases.
            #
            # This basic check can be understood as some kind of "peakiness"
            # metric. An extremely sharp peak will yield a confidence close to
            # one, whereas a broad "hill" signal will lead to lower confidence
            # values.
            max_val = weighted[0][1]
            min_val = min(self.correlate())
            mean = np.mean(self.correlate())
            weighted[0][1] = (mean - min_val) / (max_val - min_val)
        elif len(weighted) > 1:
            # The maximum confidence that can be reached in the usual
            # multi-hit situation (many possible finds) should be a combination
            # of two aspects:
            #
            # 1. How confident are we that this feature does belong somewhere
            #    into the reference at all?
            # 2. How much better is the most probable find when compared to
            #    other possible locations?
            #
            # The latter is easy to implement by comparing the highest peak to
            # the second-highest one:
            max_conf = 1 - weighted[0][1] / weighted[1][1]

            # As the other matches are obviously worse, we'll assign their
            # confidence relative to the highest one:

            # FIXME continue.

        # If `maxima` is empty, just return it.
        return weighted

    def _calc_normalization(self) -> None:
        # Calculate the reference signal normalization factors for the current
        # sample width.
        # This is necessary in order to avoid ill-fitting, high-amplitude
        # matches overpowering well-fitting low-amplitude ones.

        # "Correlate" a sample-sized slice of the reference to itself,
        # effectively calculating the norm of this section. Repeat this for
        # every possible sample placement.
        # PERF: Calculating those norms is ineffective: obviously the same
        # elements get accounted for over and over again. This is however only
        # run once for each sample size and thus usually only once at all,
        # leading to negligible perfomance impact.
        factors = np.array([np.linalg.norm(self._ref[s:s + len(self._sample)])
                            for s
                            in range(len(self._ref) - len(self._sample) + 1)])
        maxval = factors.max()
        for feat in np.nditer(factors, op_flags=['readwrite']):

            # Does this part of the reference spectrum contain actual features?
            if feat < maxval * self.feature_threshold:
                # There is no feature here. Set a high normalization divisor to
                # effectively block this section from matching anything. (1.0
                # is the highest regular divisor, see above.)
                # This part is also important to avoid division by zero
                # problems.
                feat[...] = 1.11111111

        # Cache the result.
        self._norms[len(self._sample)] = factors

    def _get_normalization(self) -> np.ndarray:
        if len(self._sample) in self._norms:
            return self._norms[len(self._sample)]

        # Normalization wasn't calculated yet for current sample length.
        self._calc_normalization()
        return self._norms[len(self._sample)]

    def _set_sample(self, sampled_points: np.ndarray, span: float) -> None:
        # Resample the data to match the references rate of sample points per 1
        # arbitrary unit.

        # We assume, that for our signal type, Akima splines present a much
        # more reasonable approximation than linear interpolation.  The
        # `length` parameter effectively determines the number of sample
        # points, as it is given with respect to the reference data length.

        # Normalize sample into the [0, 1] (inclusive) interval.
        xvals = sampled_points[0]
        xvals -= min(xvals)
        xvals /= max(xvals)

        # Create an interpolation function defined in the [0, 1] interval and
        # resample the data. We only need the new equidistant y values from now
        # on.
        inter = interpolate.Akima1DInterpolator(xvals, sampled_points[1])
        n_samples = (span / self.ref_span) * len(self.reference)
        sample = inter(np.linspace(0, 1, n_samples))

        # Normalize values for reproducible cross correllation results.
        norm = np.linalg.norm(sample)
        self._sample = np.divide(sample, norm)

        # Correllation needs to be recalculated when a new sample was set.
        self._corr = None
