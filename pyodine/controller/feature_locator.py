"""Aid in locating a given feature in a reference spectrum.

This module is a wrapper for the contained "FeatureLocator" class.
"""
import logging
from typing import Dict, List, Tuple, Union  # pylint: disable=unused-import

import numpy as np
from scipy import signal, interpolate

# 5% of max. achievable match quality are required for a local maximum in the
# cross-correlation function to be considered a match at all.
MATCH_THRESH = 0.1

# Put a positive number here. The assignment of "reliability" scores to match
# candidates is quite arbitrary. Putting a higher number here will give higher
# reliabilities and vice versa. Reliabilities will always stay in the [0, 1]
# range, of course.
CONFIDENCE_EXPONENT = 3

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

    def locate_sample(self, sample: np.ndarray, span: float) -> List[List[float]]:
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

        # Find indices where local maximums are located. Relative max's at the
        # very start and end of the corr. signal are not counted, as they
        # wouldn't give an accurate position. [0] just unpacks argrelmax's
        # return tuple.
        maxima_indices = signal.argrelmax(self.correlate())[0]
        # Scale the indices to arb. units as used in reference, add each
        # maximums value and turn the np.ndarray into a list.
        maxima = [[i / len(self._ref) * self.ref_span, self.correlate()[i]]
                  for i in maxima_indices]

        return self.rate_finds(maxima)

    def rate_finds(self, maxima: List[List[float]]) -> List[List[float]]:
        """Sort and judge the the reliability of match candidates.

        The cross correlation analysis done in this class will usually yield
        more than one candidate for positions in the reference at which a given
        signal might have originated. As *at most* one of the finds is the
        correct match, we need to provide the user with an estimation of match
        quality and reliability, which is what this function tries to give.

        Match Quality
        -------------
        Match "quality" is an indicator in [-1, 1] that comes straight from the
        cross-correlation procedure and gives an estimation of how well the
        passed sample does resemble the reference at the indicated position:

        * -1: perfect anti correlation
        * 0: no correlation
        * 1: perfect correlation

        This does *not*, however, indicate the probability that this match is
        the correct one, although the highest-quality match will always be
        tagged as the most reliable one.

        Match Reliability
        -----------------
        Match "reliability" is an indicator in [0, 1] of how probable it is
        that the match in question is the correct one when compared to other
        possible matches. If there's only one match, this tries to estimate how
        much this looks like an actual match as compared to an artifact.

        :param maxima: a list of match candidates like [<position>, <quality>]
        :returns: A list of matches like
                    [<position>, <quality>, <reliability>], sorted descending
                    by match quality. List may be empty and will not contain
                    any matches with quality below `MATCH_THRESH`.
        """
        # Sort descending by maximum height and discard matches with
        # non-positive cross-correlation. Add a column to hold the reliability
        # ratings.
        weighted = [[m[0], m[1], None]
                    for m in sorted(maxima, key=lambda n: n[1], reverse=True)
                    if m[1] > MATCH_THRESH]
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
            weighted[0][2] = (mean - min_val) / (max_val - min_val)
        elif len(weighted) > 1:
            # Estimate reliability/confidence by comparing the highest peak to
            # the second-highest one:
            max_conf = 1 - (weighted[1][1] / weighted[0][1]) ** CONFIDENCE_EXPONENT
            weighted[0][2] = max_conf

            # As the other matches are obviously worse, we'll assign their
            # confidence relative to `max_conf`, using their quality divided by
            # the main find's quality as coefficients.
            for idx in range(1, len(weighted)):
                weighted[idx][2] = max_conf * weighted[idx][1] / weighted[0][1]
        return weighted

    def _calc_normalization(self) -> None:
        """Calculate reference signal normalization factors.

        This needs to be done again for every new sample size. It is necessary
        in order to avoid ill-fitting, high-amplitude matches overpowering
        well-fitting low-amplitude ones.
        """
        # "Correlate" a sample-sized slice of the reference to itself,
        # effectively calculating the norm of this section. Repeat this for
        # every possible sample placement.

        # TODO: Calculating those norms is ineffective: obviously the same
        # elements get accounted for over and over again. While it is quite
        # obvious that this could be done in a add-one-subtract-one fashion
        # more efficiently, I'm not sure about numerical stability.
        # This is issue #138.

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
        """Resample sample data to reference rate and store it.

        For the cross-correlation approach to work, sample and reference need
        the same rate of samples per arbitrary unit.

        :param sampled_points: np array of shape (2, n) for n sampled points.
                    The first row represents the x values at which the samples
                    have been measured (don't need to be to scale with respect
                    to the reference, don't need to be equidistant). The second
                    row is the actual signal at those points.
        :param span: How many arbitrary (reference) units does the sample span?
                    This is the crucial indicator of how wide the given sample
                    is, as the actual sample point count is ignored due to
                    resampling.
        """
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
