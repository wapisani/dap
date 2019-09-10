import json
import warnings

import numpy as np

class Wavecar:
    """
    This is a class that contains the (pseudo-) wavefunctions from VASP.

    Coefficients are read from the given WAVECAR file and the corresponding
    G-vectors are generated using the algorithm developed in WaveTrans (see
    acknowledgments below). To understand how the wavefunctions are evaluated,
    please see the evaluate_wavefunc docstring.

    It should be noted that the pseudopotential augmentation is not included in
    the WAVECAR file. As a result, some caution should be exercised when
    deriving value from this information.

    The usefulness of this class is to allow the user to do projections or band
    unfolding style manipulations of the wavefunction. An example of this can
    be seen in the work of Shen et al. 2017
    (https://doi.org/10.1103/PhysRevMaterials.1.065001).

    .. attribute:: filename

        String of the input file (usually WAVECAR)

    .. attribute:: nk

        Number of k-points from the WAVECAR

    .. attribute:: nb

        Number of bands per k-point

    .. attribute:: encut

        Energy cutoff (used to define G_{cut})

    .. attribute:: efermi

        Fermi energy

    .. attribute:: a

        Primitive lattice vectors of the cell (e.g. a_1 = self.a[0, :])

    .. attribute:: b

        Reciprocal lattice vectors of the cell (e.g. b_1 = self.b[0, :])

    .. attribute:: vol

        The volume of the unit cell in real space

    .. attribute:: kpoints

        The list of k-points read from the WAVECAR file

    .. attribute:: band_energy

        The list of band eigenenergies (and corresponding occupancies) for
        each kpoint, where the first index corresponds to the index of the
        k-point (e.g. self.band_energy[kp])

    .. attribute:: Gpoints

        The list of generated G-points for each k-point (a double list), which
        are used with the coefficients for each k-point and band to recreate
        the wavefunction (e.g. self.Gpoints[kp] is the list of G-points for
        k-point kp). The G-points depend on the k-point and reciprocal lattice
        and therefore are identical for each band at the same k-point. Each
        G-point is represented by integer multipliers (e.g. assuming
        Gpoints[kp][n] == [n_1, n_2, n_3], then
        G_n = n_1*b_1 + n_2*b_2 + n_3*b_3)

    .. attribute:: coeffs

        The list of coefficients for each k-point and band for reconstructing
        the wavefunction. For non-spin-polarized, the first index corresponds
        to the kpoint and the second corresponds to the band (e.g.
        self.coeffs[kp][b] corresponds to k-point kp and band b). For
        spin-polarized calculations, the first index is for the spin.

    Acknowledgments:
        This code is based upon the Fortran program, WaveTrans, written by
        R. M. Feenstra and M. Widom from the Dept. of Physics at Carnegie
        Mellon University. To see the original work, please visit:
        https://www.andrew.cmu.edu/user/feenstra/wavetrans/

    Author: Mark Turiansky
    """

    def __init__(self, filename='WAVECAR', verbose=False, precision='normal', gamma=False):
        """
        Information is extracted from the given WAVECAR

        Args:
            filename (str): input file (default: WAVECAR)
            verbose (bool): determines whether processing information is shown
            precision (str): determines how fine the fft mesh is (normal or
                             accurate), only the first letter matters
        """
        self.filename = filename

        # c = 0.26246582250210965422
        # 2m/hbar^2 in agreement with VASP
        self._C = 0.262465831
        with open(self.filename, 'rb') as f:
            # read the header information
            recl, spin, rtag = np.fromfile(f, dtype=np.float64, count=3) \
                .astype(np.int)
            if verbose:
                print('recl={}, spin={}, rtag={}'.format(recl, spin, rtag))
            recl8 = int(recl / 8)
            self.spin = spin

            # check that ISPIN wasn't set to 2
            # if spin == 2:
            #     raise ValueError('spin polarization not currently supported')

            # check to make sure we have precision correct
            if rtag != 45200 and rtag != 45210:
                raise ValueError('invalid rtag of {}'.format(rtag))

            # padding
            np.fromfile(f, dtype=np.float64, count=(recl8 - 3))

            # extract kpoint, bands, energy, and lattice information
            self.nk, self.nb, self.encut = np.fromfile(f, dtype=np.float64,
                                                       count=3).astype(np.int)
            self.a = np.fromfile(f, dtype=np.float64, count=9).reshape((3, 3))
            self.efermi = np.fromfile(f, dtype=np.float64, count=1)[0]
            if verbose:
                print('kpoints = {}, bands = {}, energy cutoff = {}, fermi '
                      'energy= {:.04f}\n'.format(self.nk, self.nb, self.encut,
                                                 self.efermi))
                print('primitive lattice vectors = \n{}'.format(self.a))

            self.vol = np.dot(self.a[0, :],
                              np.cross(self.a[1, :], self.a[2, :]))
            if verbose:
                print('volume = {}\n'.format(self.vol))

            # calculate reciprocal lattice
            b = np.array([np.cross(self.a[1, :], self.a[2, :]),
                          np.cross(self.a[2, :], self.a[0, :]),
                          np.cross(self.a[0, :], self.a[1, :])])
            b = 2 * np.pi * b / self.vol
            self.b = b
            if verbose:
                print('reciprocal lattice vectors = \n{}'.format(b))
                print('reciprocal lattice vector magnitudes = \n{}\n'
                      .format(np.linalg.norm(b, axis=1)))

            # calculate maximum number of b vectors in each direction
            self._generate_nbmax()
            if verbose:
                print('max number of G values = {}\n\n'.format(self._nbmax))
            self.ng = self._nbmax * 3 if precision.lower()[0] == 'n' else \
                self._nbmax * 4

            # padding
            np.fromfile(f, dtype=np.float64, count=recl8 - 13)

            # reading records
            # np.set_printoptions(precision=7, suppress=True)
            self.Gpoints = [None for _ in range(self.nk)]
            self.kpoints = []
            if spin == 2:
                self.coeffs = [[[None for i in range(self.nb)]
                                for j in range(self.nk)] for _ in range(spin)]
                self.band_energy = [[] for _ in range(spin)]
            else:
                self.coeffs = [[None for i in range(self.nb)]
                               for j in range(self.nk)]
                self.band_energy = []
            for ispin in range(spin):
                if verbose:
                    print('reading spin {}'.format(ispin))
                for ink in range(self.nk):
                    # information for this kpoint
                    nplane = int(np.fromfile(f, dtype=np.float64, count=1)[0])
                    kpoint = np.fromfile(f, dtype=np.float64, count=3)

                    if ispin == 0:
                        self.kpoints.append(kpoint)
                    else:
                        assert np.allclose(self.kpoints[ink], kpoint)

                    if verbose:
                        print('kpoint {: 4} with {: 5} plane waves at {}'
                              .format(ink, nplane, kpoint))

                    # energy and occupation information
                    enocc = np.fromfile(f, dtype=np.float64,
                                        count=3 * self.nb).reshape((self.nb, 3))
                    if spin == 2:
                        self.band_energy[ispin].append(enocc)
                    else:
                        self.band_energy.append(enocc)

                    if verbose:
                        print(enocc[:, [0, 2]])

                    # padding
                    np.fromfile(f, dtype=np.float64, count=(recl8 - 4 - 3 * self.nb))

                    # generate G integers
                    self.Gpoints[ink] = self._generate_G_points(kpoint, gamma)
                    if len(self.Gpoints[ink]) != nplane:
                        raise ValueError('failed to generate the correct '
                                         'number of G points {} {}'.format(len(self.Gpoints[ink]), nplane))

                    # extract coefficients
                    for inb in range(self.nb):
                        if rtag == 45200:
                            data = np.fromfile(f, dtype=np.complex64, count=nplane)
                            np.fromfile(f, dtype=np.float64, count=recl8 - nplane)
                        elif rtag == 45210:
                            # this should handle double precision coefficients
                            # but I don't have a WAVECAR to test it with
                            data = np.fromfile(f, dtype=np.complex128, count=nplane)
                            np.fromfile(f, dtype=np.float64, count=recl8 - 2 * nplane)

                        if spin == 2:
                            self.coeffs[ispin][ink][inb] = data
                        else:
                            self.coeffs[ink][inb] = data

    def _generate_nbmax(self):
        """
        Helper function that determines maximum number of b vectors for
        each direction.

        This algorithm is adapted from WaveTrans (see Class docstring). There
        should be no reason for this function to be called outside of
        initialization.
        """
        bmag = np.linalg.norm(self.b, axis=1)
        b = self.b

        # calculate maximum integers in each direction for G
        phi12 = np.arccos(np.dot(b[0, :], b[1, :]) / (bmag[0] * bmag[1]))
        sphi123 = np.dot(b[2, :], np.cross(b[0, :], b[1, :])) / (bmag[2] * np.linalg.norm(np.cross(b[0, :], b[1, :])))
        nbmaxA = np.sqrt(self.encut * self._C) / bmag
        nbmaxA[0] /= np.abs(np.sin(phi12))
        nbmaxA[1] /= np.abs(np.sin(phi12))
        nbmaxA[2] /= np.abs(sphi123)
        nbmaxA += 1

        phi13 = np.arccos(np.dot(b[0, :], b[2, :]) / (bmag[0] * bmag[2]))
        sphi123 = np.dot(b[1, :], np.cross(b[0, :], b[2, :])) / (bmag[1] * np.linalg.norm(np.cross(b[0, :], b[2, :])))
        nbmaxB = np.sqrt(self.encut * self._C) / bmag
        nbmaxB[0] /= np.abs(np.sin(phi13))
        nbmaxB[1] /= np.abs(sphi123)
        nbmaxB[2] /= np.abs(np.sin(phi13))
        nbmaxB += 1

        phi23 = np.arccos(np.dot(b[1, :], b[2, :]) / (bmag[1] * bmag[2]))
        sphi123 = np.dot(b[0, :], np.cross(b[1, :], b[2, :])) / (bmag[0] * np.linalg.norm(np.cross(b[1, :], b[2, :])))
        nbmaxC = np.sqrt(self.encut * self._C) / bmag
        nbmaxC[0] /= np.abs(sphi123)
        nbmaxC[1] /= np.abs(np.sin(phi23))
        nbmaxC[2] /= np.abs(np.sin(phi23))
        nbmaxC += 1

        self._nbmax = np.max([nbmaxA, nbmaxB, nbmaxC], axis=0).astype(np.int)

    def _generate_G_points(self, kpoint, gamma=False):
        """
        Helper function to generate G-points based on nbmax.

        This function iterates over possible G-point values and determines
        if the energy is less than G_{cut}. Valid values are appended to
        the output array. This function should not be called outside of
        initialization.

        Args:
            kpoint (np.array): the array containing the current k-point value

        Returns:
            a list containing valid G-points
        """
        gpoints = []

        if gamma:
            kmax = self._nbmax[0] + 1
        else:
            kmax = 2 * self._nbmax[0] + 1

        for i in range(2 * self._nbmax[2] + 1):
            i3 = i - 2 * self._nbmax[2] - 1 if i > self._nbmax[2] else i
            for j in range(2 * self._nbmax[1] + 1):
                j2 = j - 2 * self._nbmax[1] - 1 if j > self._nbmax[1] else j
                for k in range(kmax):
                    k1 = k - 2 * self._nbmax[0] - 1 if k > self._nbmax[0] else k
                    if gamma and (k1 == 0 and j2 < 0) or (k1 == 0 and j2 == 0 and i3 < 0):
                        continue
                    G = np.array([k1, j2, i3])
                    v = kpoint + G
                    g = np.linalg.norm(np.dot(v, self.b))
                    E = g ** 2 / self._C
                    if E < self.encut:
                        gpoints.append(G)
        return np.array(gpoints, dtype=np.float64)

    def evaluate_wavefunc(self, kpoint, band, r, spin=0):
        r"""
        Evaluates the wavefunction for a given position, r.

        The wavefunction is given by the k-point and band. It is evaluated
        at the given position by summing over the components. Formally,

        \psi_n^k (r) = \sum_{i=1}^N c_i^{n,k} \exp (i (k + G_i^{n,k}) \cdot r)

        where \psi_n^k is the wavefunction for the nth band at k-point k, N is
        the number of plane waves, c_i^{n,k} is the ith coefficient that
        corresponds to the nth band and k-point k, and G_i^{n,k} is the ith
        G-point corresponding to k-point k.

        NOTE: This function is very slow; a discrete fourier transform is the
        preferred method of evaluation (see Wavecar.fft_mesh).

        Args:
            kpoint (int): the index of the kpoint where the wavefunction
                            will be evaluated
            band (int): the index of the band where the wavefunction will be
                            evaluated
            r (np.array): the position where the wavefunction will be evaluated
            spin (int):  spin index for the desired wavefunction (only for
                            ISPIN = 2, default = 0)
        Returns:
            a complex value corresponding to the evaluation of the wavefunction
        """
        v = self.Gpoints[kpoint] + self.kpoints[kpoint]
        u = np.dot(np.dot(v, self.b), r)
        c = self.coeffs[spin][kpoint][band] if self.spin == 2 else \
            self.coeffs[kpoint][band]
        return np.sum(np.dot(c, np.exp(1j * u, dtype=np.complex64))) / np.sqrt(self.vol)

    def fft_mesh(self, kpoint, band, spin=0, shift=True):
        """
        Places the coefficients of a wavefunction onto an fft mesh.

        Once the mesh has been obtained, a discrete fourier transform can be
        used to obtain real-space evaluation of the wavefunction. The output
        of this function can be passed directly to numpy's fft function. For
        example:

            mesh = Wavecar('WAVECAR').fft_mesh(kpoint, band)
            evals = np.fft.ifftn(mesh)

        Args:
            kpoint (int): the index of the kpoint where the wavefunction
                            will be evaluated
            band (int): the index of the band where the wavefunction will be
                            evaluated
            spin (int):  the spin of the wavefunction for the desired
                            wavefunction (only for ISPIN = 2, default = 0)
            shift (bool): determines if the zero frequency coefficient is
                            placed at index (0, 0, 0) or centered
        Returns:
            a numpy ndarray representing the 3D mesh of coefficients
        """
        mesh = np.zeros(tuple(self.ng), dtype=np.complex)
        tcoeffs = self.coeffs[spin][kpoint][band] if self.spin == 2 else \
            self.coeffs[kpoint][band]
        for gp, coeff in zip(self.Gpoints[kpoint], tcoeffs):
            t = tuple(gp.astype(np.int) + (self.ng / 2).astype(np.int))
            mesh[t] = coeff
            if tuple(gp.astype(int)) != (0,0,0):
                t = tuple(-gp.astype(np.int) + (self.ng / 2).astype(np.int))
                mesh[t] = np.conj(coeff)
        if shift:
            return np.fft.ifftshift(mesh)
        else:
            return mesh

    def get_parchg(self, poscar, kpoint, band, spin=None, phase=False,
                   scale=2):
        """
        Generates a Chgcar object, which is the charge density of the specified
        wavefunction.

        This function generates a Chgcar object with the charge density of the
        wavefunction specified by band and kpoint (and spin, if the WAVECAR
        corresponds to a spin-polarized calculation). The phase tag is a
        feature that is not present in VASP. For a real wavefunction, the phase
        tag being turned on means that the charge density is multiplied by the
        sign of the wavefunction at that point in space. A warning is generated
        if the phase tag is on and the chosen kpoint is not Gamma.

        Note: Augmentation from the PAWs is NOT included in this function. The
        maximal charge density will differ from the PARCHG from VASP, but the
        qualitative shape of the charge density will match.

        Args:
            poscar (pymatgen.io.vasp.inputs.Poscar): Poscar object that has the
                                structure associated with the WAVECAR file
            kpoint (int):   the index of the kpoint for the wavefunction
            band (int):     the index of the band for the wavefunction
            spin (int):     optional argument to specify the spin. If the
                                Wavecar has ISPIN = 2, spin is None generates a
                                Chgcar with total spin and magnetization, and
                                spin == {0, 1} specifies just the spin up or
                                down component.
            phase (bool):   flag to determine if the charge density is
                                multiplied by the sign of the wavefunction.
                                Only valid for real wavefunctions.
            scale (int):    scaling for the FFT grid. The default value of 2 is
                                at least as fine as the VASP default.
        Returns:
            a pymatgen.io.vasp.outputs.Chgcar object
        """

        if phase and not np.all(self.kpoints[kpoint] == 0.):
            warnings.warn('phase == True should only be used for the Gamma '
                          'kpoint! I hope you know what you\'re doing!')

        # scaling of ng for the fft grid, need to restore value at the end
        temp_ng = self.ng
        self.ng = self.ng * scale
        N = np.prod(self.ng)

        data = {}
        if self.spin == 2:
            if spin is not None:
                wfr = np.fft.ifftn(self.fft_mesh(kpoint, band, spin=spin)) * N
                den = np.abs(np.conj(wfr) * wfr)
                if phase:
                    den = np.sign(np.real(wfr)) * den
                data['total'] = den
            else:
                wfr = np.fft.ifftn(self.fft_mesh(kpoint, band, spin=0)) * N
                denup = np.abs(np.conj(wfr) * wfr)
                wfr = np.fft.ifftn(self.fft_mesh(kpoint, band, spin=1)) * N
                dendn = np.abs(np.conj(wfr) * wfr)
                data['total'] = denup + dendn
                data['diff'] = denup - dendn
        else:
            wfr = np.fft.ifftn(self.fft_mesh(kpoint, band)) * N
            den = np.abs(np.conj(wfr) * wfr)
            if phase:
                den = np.sign(np.real(wfr)) * den
            data['total'] = den

        self.ng = temp_ng
        return Chgcar(poscar, data)