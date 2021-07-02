# This code is part of Qiskit.
#
# (C) Copyright IBM 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""The ElectronicEnergy property."""

from copy import deepcopy
from typing import Dict, List, Optional, Tuple

import numpy as np

from qiskit_nature.operators.second_quantization import FermionicOp

from ...second_quantized_property import DriverResult, SecondQuantizedProperty
from ..bases import ElectronicBasis, ElectronicBasisTransform
from . import ElectronicIntegrals


class IntegralProperty(SecondQuantizedProperty):
    """A common Property object based on `ElectronicIntegrals` as its raw data.

    This is a common base class, extracted to be used by (at the time of writing) the
    `ElectronicEnergy` and the `DipoleMoment` properties. More subclasses may be added in the
    future.
    """

    def __init__(
        self,
        name: str,
        electronic_integrals: Dict[ElectronicBasis, List[ElectronicIntegrals]],
        shift: Optional[Dict[str, float]] = None,
    ):
        """
        Args:
            basis: the basis which the integrals in ``electronic_integrals`` are stored in.
            electronic_integrals: a dictionary mapping the ``# body terms`` to the corresponding
                ``ElectronicIntegrals``.
            shift: an optional dictionary of value shifts.
        """
        super().__init__(name)
        self._electronic_integrals = electronic_integrals
        self._shift = shift or {}

    def second_q_ops(self) -> List[FermionicOp]:
        """Returns a list containing the Hamiltonian constructed by the stored electronic integrals."""
        ints = None
        if ElectronicBasis.SO in self._electronic_integrals.keys():
            ints = self._electronic_integrals[ElectronicBasis.SO]
        elif ElectronicBasis.MO in self._electronic_integrals.keys():
            ints = self._electronic_integrals[ElectronicBasis.MO]
        return [sum(int.to_second_q_op() for int in ints).reduce()]  # type: ignore

    @classmethod
    def from_driver_result(cls, result: DriverResult) -> "IntegralProperty":
        """This property does not support construction from a driver result (yet).

        Args:
            result: ignored.

        Raises:
            NotImplemented
        """
        raise NotImplementedError()
