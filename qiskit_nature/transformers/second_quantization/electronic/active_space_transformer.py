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

"""The Active-Space Reduction interface."""

import copy
from typing import List, Optional, Tuple, Union

import numpy as np

from qiskit_nature import QiskitNatureError
from qiskit_nature.drivers.second_quantization import QMolecule
from qiskit_nature.properties.second_quantization.electronic import \
    ParticleNumber
from qiskit_nature.properties.second_quantization.electronic.bases import (
    ElectronicBasis, ElectronicBasisTransform)
from qiskit_nature.properties.second_quantization.electronic.electronic_driver_result import \
    ElectronicDriverResult
from qiskit_nature.properties.second_quantization.electronic.integrals import \
    IntegralProperty

from ..base_transformer import BaseTransformer

ACTIVE_INTS_SUBSCRIPT = "pqrs,pi,qj,rk,sl->ijkl"

INACTIVE_ENERGY_SUBSCRIPT = "ij,ji"


class ActiveSpaceTransformer(BaseTransformer):
    r"""The Active-Space reduction.

    The reduction is done by computing the inactive Fock operator which is defined as
    :math:`F^I_{pq} = h_{pq} + \sum_i 2 g_{iipq} - g_{iqpi}` and the inactive energy which is
    given by :math:`E^I = \sum_j h_{jj} + F ^I_{jj}`, where :math:`i` and :math:`j` iterate over
    the inactive orbitals.
    By using the inactive Fock operator in place of the one-electron integrals, `h1`, the
    description of the active space contains an effective potential generated by the inactive
    electrons. Therefore, this method permits the exclusion of non-core electrons while
    retaining a high-quality description of the system.

    For more details on the computation of the inactive Fock operator refer to
    https://arxiv.org/abs/2009.01872.

    The active space can be configured in one of the following ways through the initializer:
        - when only `num_electrons` and `num_molecular_orbitals` are specified, these integers
          indicate the number of active electrons and orbitals, respectively. The active space will
          then be chosen around the Fermi level resulting in a unique choice for any pair of
          numbers.  Nonetheless, the following criteria must be met:

            #. the remaining number of inactive electrons must be a positive, even number

            #. the number of active orbitals must not exceed the total number of orbitals minus the
               number of orbitals occupied by the inactive electrons

        - when, in addition to the above, `num_alpha` is specified, this can be used to disambiguate
          the active space in systems with non-zero spin. Thus, `num_alpha` determines the number of
          active alpha electrons. The number of active beta electrons can then be determined based
          via `num_beta = num_electrons - num_alpha`. The same requirements as listed in the
          previous case must be met.
        - finally, it is possible to select a custom set of active orbitals via their indices using
          `active_orbitals`. This allows selecting an active space which is not placed around the
          Fermi level as described in the first case, above. When using this keyword argument, the
          following criteria must be met *in addition* to the ones listed above:

            #. the length of `active_orbitals` must be equal to `num_molecular_orbitals`.

            #. the sum of electrons present in `active_orbitals` must be equal to `num_electrons`.

    References:
        - *M. Rossmannek, P. Barkoutsos, P. Ollitrault, and I. Tavernelli, arXiv:2009.01872
          (2020).*
    """

    def __init__(
        self,
        num_electrons: Optional[Union[int, Tuple[int, int]]] = None,
        num_molecular_orbitals: Optional[int] = None,
        active_orbitals: Optional[List[int]] = None,
    ):
        """Initializes a transformer which can reduce a `QMolecule` to a configured active space.

        This transformer requires the AO-basis matrices `hcore` and `eri` to be available, as well
        as the basis-transformation matrix `mo_coeff`. A `QMolecule` produced by Qiskit's drivers in
        general satisfies these conditions unless it was read from an FCIDump file. However, those
        integrals are likely already reduced by the code which produced the file or can be
        transformed using this driver after copying the MO-basis integrals of the produced
        `QMolecule` into the AO-basis containers and initializing `mo_coeff` with an identity matrix
        of appropriate size.

        Args:
            num_electrons: The number of active electrons. If this is a tuple, it represents the
                           number of alpha and beta electrons. If this is a number, it is
                           interpreted as the total number of active electrons, should be even, and
                           implies that the number of alpha and beta electrons equals half of this
                           value, respectively.
            num_molecular_orbitals: The number of active orbitals.
            active_orbitals: A list of indices specifying the molecular orbitals of the active
                             space. This argument must match with the remaining arguments and should
                             only be used to enforce an active space that is not chosen purely
                             around the Fermi level.
        """
        self._num_electrons = num_electrons
        self._num_molecular_orbitals = num_molecular_orbitals
        self._active_orbitals = active_orbitals

        self._mo_occ_total: np.ndarray = None
        self._num_particles: Tuple[int, int] = None

    def transform(self, molecule_data: ElectronicDriverResult) -> ElectronicDriverResult:
        """Reduces the given `QMolecule` to a given active space.

        Args:
            molecule_data: the `QMolecule` to be transformed.

        Returns:
            A new `QMolecule` instance.

        Raises:
            QiskitNatureError: If more electrons or orbitals are requested than are available, if an
                               uneven number of inactive electrons remains, or if the number of
                               selected active orbital indices does not match
                               `num_molecular_orbitals`.
        """
        try:
            self._check_configuration()
        except QiskitNatureError as exc:
            raise QiskitNatureError("Incorrect Active-Space configuration.") from exc

        # get molecular orbital coefficients
        mo_coeff_full = (
            molecule_data.electronic_basis_transform.coeff_alpha,
            molecule_data.electronic_basis_transform.coeff_beta,
        )
        beta_spin = np.allclose(mo_coeff_full[0], mo_coeff_full[1])
        # get molecular orbital occupation numbers
        mo_occ_full = (
            np.asarray(molecule_data.properties["ParticleNumber"]._occupation_alpha),
            np.asarray(molecule_data.properties["ParticleNumber"]._occupation_beta),
        )
        self._mo_occ_total = mo_occ_full[0] + mo_occ_full[1]

        active_orbs_idxs, inactive_orbs_idxs = self._determine_active_space(molecule_data)

        # split molecular orbitals coefficients into active and inactive parts

        mo_occ_inactive_a = mo_occ_full[0][inactive_orbs_idxs]
        mo_coeff_inactive_a = mo_coeff_full[0][:, inactive_orbs_idxs]
        density_inactive_a = np.dot(
            mo_coeff_inactive_a * mo_occ_inactive_a,
            np.transpose(mo_coeff_inactive_a),
        )

        density_inactive_b = None

        if beta_spin:
            mo_occ_inactive_b = mo_occ_full[1][inactive_orbs_idxs]
            mo_coeff_inactive_b = mo_coeff_full[1][:, inactive_orbs_idxs]
            density_inactive_b = np.dot(
                mo_coeff_inactive_b * mo_occ_inactive_b,
                np.transpose(mo_coeff_inactive_b),
            )

        density_inactive = (density_inactive_a, density_inactive_b)

        transform = ElectronicBasisTransform(
            ElectronicBasis.AO,
            ElectronicBasis.MO,
            mo_coeff_full[0][:, active_orbs_idxs],
            mo_coeff_full[1][:, active_orbs_idxs] if beta_spin else None,
        )

        # construct new QMolecule
        molecule_data_reduced = ElectronicDriverResult()

        for prop in molecule_data.properties.values():
            try:
                reduced_prop = prop.reduce_system_size(density_inactive, transform)
            except NotImplementedError:
                continue

            molecule_data_reduced.add_property(reduced_prop)

        molecule_data_reduced.properties["ParticleNumber"] = ParticleNumber(
            self._num_molecular_orbitals // 2,
            self._num_particles,
            mo_occ_full[0][active_orbs_idxs],
            mo_occ_full[1][active_orbs_idxs],
        )

        return molecule_data_reduced

    def _check_configuration(self):
        if isinstance(self._num_electrons, int):
            if self._num_electrons % 2 != 0:
                raise QiskitNatureError(
                    "The number of active electrons must be even! Otherwise you must specify them "
                    "as a tuple, not as:",
                    str(self._num_electrons),
                )
            if self._num_electrons < 0:
                raise QiskitNatureError(
                    "The number of active electrons cannot be negative:",
                    str(self._num_electrons),
                )
        elif isinstance(self._num_electrons, tuple):
            if not all(isinstance(n_elec, int) and n_elec >= 0 for n_elec in self._num_electrons):
                raise QiskitNatureError(
                    "Neither the number of alpha, nor the number of beta electrons can be "
                    "negative:",
                    str(self._num_electrons),
                )
        else:
            raise QiskitNatureError(
                "The number of active electrons must be an int, or a tuple thereof, not:",
                str(self._num_electrons),
            )

        if isinstance(self._num_molecular_orbitals, int):
            if self._num_molecular_orbitals < 0:
                raise QiskitNatureError(
                    "The number of active orbitals cannot be negative:",
                    str(self._num_molecular_orbitals),
                )
        else:
            raise QiskitNatureError(
                "The number of active orbitals must be an int, not:",
                str(self._num_electrons),
            )

    def _determine_active_space(self, molecule_data: QMolecule):
        if isinstance(self._num_electrons, tuple):
            num_alpha, num_beta = self._num_electrons
        elif isinstance(self._num_electrons, int):
            num_alpha = num_beta = self._num_electrons // 2

        # compute number of inactive electrons
        nelec_total = (
            molecule_data.properties["ParticleNumber"]._num_alpha
            + molecule_data.properties["ParticleNumber"]._num_beta
        )
        nelec_inactive = nelec_total - num_alpha - num_beta

        self._num_particles = (num_alpha, num_beta)

        self._validate_num_electrons(nelec_inactive)
        self._validate_num_orbitals(nelec_inactive, molecule_data)

        # determine active and inactive orbital indices
        if self._active_orbitals is None:
            norbs_inactive = nelec_inactive // 2
            inactive_orbs_idxs = list(range(norbs_inactive))
            active_orbs_idxs = list(
                range(norbs_inactive, norbs_inactive + self._num_molecular_orbitals)
            )
        else:
            active_orbs_idxs = self._active_orbitals
            inactive_orbs_idxs = [
                o
                for o in range(nelec_total // 2)
                if o not in self._active_orbitals and self._mo_occ_total[o] > 0
            ]

        return (active_orbs_idxs, inactive_orbs_idxs)

    def _validate_num_electrons(self, nelec_inactive: int):
        """Validates the number of electrons.

        Args:
            nelec_inactive: the computed number of inactive electrons.

        Raises:
            QiskitNatureError: if the number of inactive electrons is either negative or odd.
        """
        if nelec_inactive < 0:
            raise QiskitNatureError("More electrons requested than available.")
        if nelec_inactive % 2 != 0:
            raise QiskitNatureError("The number of inactive electrons must be even.")

    def _validate_num_orbitals(self, nelec_inactive: int, molecule_data: QMolecule):
        """Validates the number of orbitals.

        Args:
            nelec_inactive: the computed number of inactive electrons.
            molecule_data: the `QMolecule` to be transformed.

        Raises:
            QiskitNatureError: if more orbitals were requested than are available in total or if the
                               number of selected orbitals mismatches the specified number of active
                               orbitals.
        """
        if self._active_orbitals is None:
            norbs_inactive = nelec_inactive // 2
            if (
                norbs_inactive + self._num_molecular_orbitals
                > molecule_data.properties["ParticleNumber"]._num_spin_orbitals // 2
            ):
                raise QiskitNatureError("More orbitals requested than available.")
        else:
            if self._num_molecular_orbitals != len(self._active_orbitals):
                raise QiskitNatureError(
                    "The number of selected active orbital indices does not "
                    "match the specified number of active orbitals."
                )
            if (
                max(self._active_orbitals)
                >= molecule_data.properties["ParticleNumber"]._num_spin_orbitals // 2
            ):
                raise QiskitNatureError("More orbitals requested than available.")
            if sum(self._mo_occ_total[self._active_orbitals]) != self._num_electrons:
                raise QiskitNatureError(
                    "The number of electrons in the selected active orbitals "
                    "does not match the specified number of active electrons."
                )