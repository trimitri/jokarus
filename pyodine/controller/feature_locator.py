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
        # located. We need to set the mode to 'wrap' in order to also catch
        # relative max's at the very start and end of the corr. signal.
        relative_maxima_positions = signal.argrelmax(self.correlate(), mode='wrap')[0]
        maxima = [self.correlate()[i] for i in relative_maxima_positions]
        maxima = np.sort(maxima)
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
