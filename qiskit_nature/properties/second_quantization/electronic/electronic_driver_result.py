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

"""The ElectronicDriverResult class."""

from typing import Dict, List, cast

from qiskit_nature.drivers.second_quantization import QMolecule
from qiskit_nature.operators.second_quantization import FermionicOp

from ..second_quantized_property import DriverResult, SecondQuantizedProperty
from ..second_quantized_property import ElectronicDriverResult as LegacyElectronicDriverResult
from .angular_momentum import AngularMomentum
from .bases import ElectronicBasis, ElectronicBasisTransform
from .dipole_moment import DipoleMoment, TotalDipoleMoment
from .electronic_energy import ElectronicEnergy
from .integrals import OneBodyElectronicIntegrals, TwoBodyElectronicIntegrals
from .magnetization import Magnetization
from .particle_number import ParticleNumber


class ElectronicDriverResult(SecondQuantizedProperty):
    """TODO."""

    def __init__(self) -> None:
        """TODO."""
        super().__init__(self.__class__.__name__)
        self.properties: Dict[str, SecondQuantizedProperty] = {}
        self.electronic_basis_transform: ElectronicBasisTransform = None
        # TODO: add origin driver metadata
        # TODO: where to put orbital_energies?
        # TODO: add molecule geometry metadata
        # TODO: where to put kinetic, overlap matrices? Do we want explicit Fock matrix?

    def add_property(self, prop: SecondQuantizedProperty) -> None:
        """TODO."""
        self.properties[prop.name] = prop

    @classmethod
    def from_driver_result(cls, result: DriverResult) -> "ElectronicDriverResult":
        """TODO."""
        cls._validate_input_type(result, LegacyElectronicDriverResult)

        ret = cls()

        qmol = cast(QMolecule, result)

        ret.add_property(ElectronicEnergy.from_driver_result(qmol))
        ret.add_property(ParticleNumber.from_driver_result(qmol))
        ret.add_property(AngularMomentum.from_driver_result(qmol))
        ret.add_property(Magnetization.from_driver_result(qmol))
        ret.add_property(TotalDipoleMoment.from_driver_result(qmol))

        ret.add_property(ElectronicEnergy(
            ElectronicBasis.AO,
            {
                1: OneBodyElectronicIntegrals(ElectronicBasis.AO, (qmol.hcore, qmol.hcore_b)),
                2: TwoBodyElectronicIntegrals(ElectronicBasis.AO, (qmol.eri, None, None, None)),
            },
        ))

        def dipole_along_axis(axis, ao_ints):
            return DipoleMoment(
                axis,
                ElectronicBasis.AO,
                {1: OneBodyElectronicIntegrals(ElectronicBasis.AO, ao_ints)},
            )

        ret.add_property(TotalDipoleMoment(
            {
                "x": dipole_along_axis("x", (qmol.x_dip_ints, None)),
                "y": dipole_along_axis("y", (qmol.y_dip_ints, None)),
                "z": dipole_along_axis("z", (qmol.z_dip_ints, None)),
            }
        ))

        ret.electronic_basis_transform = ElectronicBasisTransform(
            ElectronicBasis.AO, ElectronicBasis.MO, qmol.mo_coeff, qmol.mo_coeff_b
        )

        return ret

    def second_q_ops(self) -> List[FermionicOp]:
        """TODO."""
        ops: List[FermionicOp] = []
        ops.extend(self.electronic_energy_mo.second_q_ops())
        ops.extend(self.particle_number.second_q_ops())
        ops.extend(self.angular_momentum.second_q_ops())
        ops.extend(self.magnetization.second_q_ops())
        ops.extend(self.total_dipole_moment.second_q_ops())
        return ops
