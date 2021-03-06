#!/usr/bin/python
# Robert Lindner
# Autonomous Gaussian Decomposition

# Standard Libs
import time

# Standard Third Party
import numpy as np
import math
from scipy.interpolate import interp1d
from scipy.special import factorial
# from scipy.optimize import leastsq, minimize
from lmfit import minimize as lmfit_minimize
from lmfit import Parameters

# import matplotlib.pyplot as plt
from numpy.linalg import lstsq
from scipy.ndimage.filters import median_filter, convolve

# Python Regularized derivatives
from . import tvdiff


def vals_vec_from_lmfit(lmfit_params):
    """ Return Python list of parameter values from LMFIT Parameters object"""
    vals = [value.value for value in lmfit_params.values()]
    return vals


def errs_vec_from_lmfit(lmfit_params):
    """ Return Python list of parameter uncertainties from LMFIT Parameters object"""
    errs = [value.stderr for value in lmfit_params.values()]
    return errs


def paramvec_to_lmfit(paramvec):
    ncomps = len(paramvec) // 3
    params = Parameters()
    for i in range(len(paramvec)):
        # print(paramvec)
        # print(paramvec[i])
        # print(i)
        if i < ncomps:
            # params.add("p" + str(i + 1), value=paramvec[i], min=0., max=5, brute_step=1)
            params.add("p" + str(i + 1), value=paramvec[i],min=0,max=paramvec[i])
        elif i < 2*ncomps-1:
            params.add("p" + str(i + 1), value=paramvec[i],min=-10,max=10.)
        elif i == 2*ncomps-1:
            # print(i+ncomps-1)
            params.add("p" + str(i + 1), value=paramvec[i],min=-10,max=10)
        else:
            # print(paramvec[i])
            params.add("p" + str(i + 1), value=paramvec[i],min=paramvec[i]-0.1,max=paramvec[i])

    return params


def create_fitmask(size, offsets_i, di):
    """ Return valid domain for intermediate fit in d2/dx2 space

     fitmask = (0,1)
     fitmaskw = (True, False)
     """
    fitmask = np.zeros(size)
    for i in range(len(offsets_i)):
        fitmask[int(offsets_i[i] - di[i]): int(offsets_i[i] + di[i])] = 1.0
    fitmaskw = fitmask == 1.0
    return fitmask, fitmaskw


def say(message, verbose=False):
    """ Diagnostic messages
    """
    if verbose:
        print(message)


def gaussian(peak, FWHM, mean):
    """Return a Gaussian function
    """
    # Peak = Amplitude -> A_0
    # FWHM = Width -> k
    # mean = centre -> heavyside
    #sigma = FWHM / 2.354820045  # (2 * sqrt( 2 * ln(2)))
    # return lambda x: np.where((x) < (mean),0,peak * 1/((x-mean) ** (1/FWHM)))  

    #return lambda x: np.where((x) > (mean+FWHM*math.pi/(2)),0,np.where((x) < (mean),0,-peak * np.tan((x/FWHM + math.pi/2 - mean))))
    return lambda x: np.where((x) < (mean),0,peak * np.exp(- (x-mean) / np.exp(FWHM)))
    # return lambda x: np.where((x) < (mean),1e-5,peak*np.exp(-((x-mean)*np.exp((x-mean)))**(1/FWHM)))

    #return lambda x: np.where((x) < (mean),1e-5,FWHM*  (x-mean) ** (-1/peak))
    # return lambda x: np.where((-(x/FWHM-mean-1)**5 * (peak))<=0,0,np.where(((x) <= (mean)),0,-(x/FWHM-mean-1)**5 * (peak))) 
    # return lambda x: np.where((-peak* (x-mean-1)**21)<=0,0,np.where(((x) < (mean)),0,-peak* (x-mean-1)**21))
    #return lambda x: np.where((x)<mean, 0,np.where(FWHM ==0,0,peak / factorial((x-mean) / FWHM)))
def gaussian2(peak, FWHM, mean):
    """Return a Gaussian function
    """
    # Peak = Amplitude -> A_0
    # FWHM = Width -> k
    # mean = centre -> heavyside
    #sigma = FWHM / 2.354820045  # (2 * sqrt( 2 * ln(2)))
    # return lambda x: np.where((x) < (mean),0,peak * 1/((x-mean) ** 1/(FWHM)))  

    #return lambda x: np.where((x) > (mean+FWHM*math.pi/(2)),0,np.where((x) < (mean),0,-peak * np.tan((x/FWHM + math.pi/2 - mean))))
    # return lambda x: np.where((x) < (mean),1e-5,peak * np.exp(- (x-mean) / (FWHM)))
    #return lambda x: np.where((x) < (mean),1e-5,peak*np.exp(-((x-mean)*np.exp((x-mean)))**(1/FWHM)))

    #return lambda x: np.where((x) < (mean),1e-5,FWHM*  (x-mean) ** (-1/peak))
    return lambda x: np.where((-(x-mean) / FWHM + (peak))<=0,0,np.where(((x) <= (mean)),0,-(x-mean) / FWHM + (peak))) 
    #return lambda x: np.where((x)<mean, 0,np.where(FWHM ==0,0,peak / factorial((x-mean) / FWHM)))


def func(x, *args):
    """ Return multi-component Gaussian model F(x).

    Parameter vector kargs = [amp1, ..., ampN, width1, ..., widthN, mean1, ..., meanN],
    and therefore has len(args) = 3 x N_components.
    """
    ncomps = len(args) // 3
    yout = np.zeros(len(x))
    for i in range(ncomps):
        yout = yout + gaussian(args[i], args[i + ncomps], args[i + 2 * ncomps])(x)
        #if i == 1:
        #    print(max(args[1+2*ncomps:1+3*ncomps]))
        #    yout = yout + gaussian2(args[i], args[i + ncomps], args[i + 2 * ncomps])(x)
        #else:
        #    yout = yout + gaussian(args[i], args[i + ncomps], args[i + 2 * ncomps])(x)

    return yout


def fvel_init(
        ind,
        data,
):
    # This takes the index, finds the index of the maximum value surrounding that index and returns the assasiated x value
    new_ind=np.array([],dtype="int")
    for i in ind:
        all_data = [data[i-3],data[i-2],data[i-1],data[i],data[i+1],data[i+2],data[i+3]]
        # print(all_data)
        # print(max(all_data))
        if all_data[0] == max(all_data):
            new_ind=np.append(new_ind,[i-3]) 
        elif all_data[1] == max(all_data):
            new_ind=np.append(new_ind,[i-2]) 
        elif all_data[2] == max(all_data):
            new_ind=np.append(new_ind,[i-1]) 
        elif all_data[3] == max(all_data):
            new_ind=np.append(new_ind,[i]) 
        elif all_data[4] == max(all_data):
            new_ind=np.append(new_ind,[i+1]) 
        elif all_data[5] == max(all_data):
            new_ind=np.append(new_ind,[i+2]) 
        else:
            new_ind=np.append(new_ind,[i+3]) 
      # Converts from index -> x domain
    # print(ind)
    # print(data[ind])
    # print(new_ind)
    # print(data[new_ind])
    return new_ind

def initialGuess(
    vel,
    data,
    errors=None,
    alpha=None,
    # plot=False,
    mode="python",
    verbose=False,
    SNR_thresh=5.0,
    BLFrac=0.1,
    SNR2_thresh=5.0,
    deblend=True,
):
    """  Find initial parameter guesses (AGD algorithm)

    data,             Input data
    dv,             x-spacing absolute units
    alpha = No Default,     regularization parameter
    plot = False,     Show diagnostic plots?
    verbose = True    Diagnostic messages
    SNR_thresh = 5.0  Initial Spectrum S/N threshold
    BLFrac =          Edge fraction of data used for S/N threshold computation
    SNR2_thresh =   S/N threshold for Second derivative
    mode = Method for taking derivatives
    """

    errors = None  # Until error

    # print("data")
    # print(data)
    # print("vel")
    # print(vel)
    say("\n\n  --> initialGuess() \n", verbose)
    say("Algorithm parameters: ", verbose)
    say("alpha = {0}".format(alpha), verbose)
    say("SNR_thesh = {0}".format(SNR_thresh), verbose)
    say("SNR2_thesh = {0}".format(SNR2_thresh), verbose)
    say("BLFrac = {0}".format(BLFrac), verbose)

    if not alpha:
        print("Must choose value for alpha, no default.")
        return

    if np.any(np.isnan(data)):
        print("NaN-values in data, cannot continue.")
        return

    # Data inspection
    vel = np.array(vel)
    # print("vel")
    # print(vel)
    data = np.array(data)
    dv = np.abs(vel[1] - vel[0])
    fvel = interp1d(np.arange(len(vel)), vel)  # Converts from index -> x domain
    data_size = len(data)

    # Take regularized derivatives
    t0 = time.time()
    if mode == "python":
        say("Taking python derivatives...", verbose)
        u = tvdiff.TVdiff(data, dx=dv, alph=alpha)
        #print(u)
        u2 = tvdiff.TVdiff(u, dx=dv, alph=alpha)
        #print(u2)
        u3 = tvdiff.TVdiff(u2, dx=dv, alph=alpha)
        #print(u3)
        u4 = tvdiff.TVdiff(u3, dx=dv, alph=alpha)
        #print(u4)
        # print("u----------------------------")
        # print(u)
        # print("u2----------------------------")
        # print(u2)
        # print("u3----------------------------")
        # print(u3)
        # print("u4----------------------------")
        # print(u4)
        # print("here1")
    elif mode == "conv":
        say("Convolution sigma [pixels]: {0}".format(alpha), verbose)
        gauss_sigma = alpha
        gauss_sigma_int = np.max([np.fix(gauss_sigma), 5])
        gauss_dn = gauss_sigma_int * 6

        print("here")
        xx = np.arange(2 * gauss_dn + 2) - (gauss_dn) - 0.5
        gauss = np.exp(-xx ** 2 / 2.0 / gauss_sigma ** 2)
        gauss = gauss / np.sum(gauss)
        gauss1 = np.diff(gauss) / dv
        gauss3 = np.diff(np.diff(gauss1)) / dv ** 2

        xx2 = np.arange(2 * gauss_dn + 1) - (gauss_dn)
        gauss2 = np.exp(-xx2 ** 2 / 2.0 / gauss_sigma ** 2)
        gauss2 = gauss2 / np.sum(gauss2)
        gauss2 = np.diff(gauss2) / dv

        data,gauss2 = np.diff(gauss2) / dv
        gauss4 = np.diff(np.diff(gauss2)) / dv ** 2

        u = convolve(data, gauss1, mode="wrap")
        u2 = convolve(data, gauss2, mode="wrap")
        u3 = convolve(data, gauss3, mode="wrap")
        u4 = convolve(data, gauss4, mode="wrap")

    say(
        "...took {0:4.2f} seconds per derivative.".format((time.time() - t0) / 4.0),
        verbose,
    )

    # Decide on signal threshold
    if not errors:
        errors = np.std(data[0: int(BLFrac * data_size)])

    thresh = SNR_thresh * errors
    mask1 = np.array(data > thresh, dtype="int")[1:]  # Raw Data S/N
    mask3 = np.array(u4.copy()[1:] > 0.0, dtype="int")  # Positive 4nd derivative

    if SNR2_thresh > 0.0:
        wsort = np.argsort(np.abs(u2))
        RMSD2 = (
            np.std(u2[wsort[0: int(0.5 * len(u2))]]) / 0.377
        )  # RMS based in +-1 sigma fluctuations
        say("Second derivative noise: {0}".format(RMSD2), verbose)
        thresh2 = -RMSD2 * SNR2_thresh
        say("Second derivative threshold: {0}".format(thresh2), verbose)
    else:
        thresh2 = 0.0

    # print("Thresh")
    print(-1/SNR_thresh)
    mask4 = np.array(u2.copy()[1:] < -1/SNR_thresh, dtype="int")  # Negative second derivative
    # mask4 = np.array(u2.copy()[1:] < -2.4, dtype="int")  # Negative second derivative

    # Find optima of second derivative
    # --------------------------------
    # print(mask4)
    # print(mask1)
    # print(mask3)
    # zeros = np.abs(np.diff(np.sign(u3)))
    zeros = np.array(np.diff(np.sign(u3))>0,dtype="int")
    # zeros = np.abs((np.diff(u2)))
    # print(zeros)
    # zeros = zeros * mask4 * mask1* mask3
    zeros = zeros*mask4
    offsets_data_i = np.array(np.where(zeros)).ravel()  # Index offsets

    offsets = fvel(fvel_init(offsets_data_i,data))  # Velocity offsets (Added 0.5 July 23)
    N_components = len(offsets)
    say(
        "Components found for alpha={1}: {0}".format(N_components, alpha),
        verbose=verbose,
    )

    # Check if nothing was found, if so, return null
    # ----------------------------------------------
    if N_components == 0:
        odict = {
            "means": [],
            "FWHMs": [],
            "amps": [],
            "u2": u2,
            "errors": errors,
            "thresh2": thresh2,
            "thresh": thresh,
            "N_components": N_components,
        }

        return odict

    #        say('AGD2.initialGuess: No components found for alpha={0}! Returning ([] [] [] [] [])'.format(alpha))
    #        return [], [], [], u2

    # Find Relative widths, then measure
    # peak-to-inflection distance for sharpest peak
    widths = np.sqrt(np.abs(data/u2)[offsets_data_i])
    # widths = np.sqrt(np.abs(data / u2)[offsets_data_i])
    FWHMs = widths *2.355

    # Attempt deblending.
    # If Deblending results in all non-negative answers, keep.
    amps = np.array(data[fvel_init(offsets_data_i,data)])
    print("here")
    print(offsets)
    # print(amps)
    # if deblend:
    #     FF_matrix = np.zeros([len(amps), len(amps)])
    #     for i in range(FF_matrix.shape[0]):
    #         for j in range(FF_matrix.shape[1]):
    #             #FF_matrix[i, j] = np.where(offsets[i]<offsets[j],0,amps[j]*np.exp(-((offsets[i] - offsets[j])*np.exp(-(offsets[i] - offsets[j])))**(1/FWHMs[j])))
    #             #FF_matrix[i, j] = np.where(offsets[i]<offsets[j],0,amps[j]*np.exp(-((offsets[i] - offsets[j])*np.exp(-(offsets[i] - offsets[j])))**(1/FWHMs[j])))
    #             FF_matrix[i, j] = np.where(offsets[i]<offsets[j],0,np.exp(-(offsets[i] - offsets[j])/(FWHMs[j])))
    #              # FF_matrix[i,j] = np.where((- (amps[j])* (offsets[i]-offsets[j]-1)**21)<=0,0,np.where(((offsets[i]) < (offsets[j])),0,- amps[j]* (offsets[i]-offsets[j]-1)**21)) 
    #             # FF_matrix[i, j] = np.exp(
    #             #     -(offsets[i] - offsets[j]) ** 2 / 2.0 / (FWHMs[j] / 2.355) ** 2
    #             # )
    #     amps_new = lstsq(FF_matrix, amps, rcond=None)[0]
    #     if np.all(amps_new > 0):
    #         amps = amps_new
    # print(offsets)
    odict = {
        "means": offsets,
        "FWHMs": FWHMs,
        "amps": amps,
        "u2": u2,
        "errors": errors,
        "thresh2": thresh2,
        "thresh": thresh,
        "N_components": N_components,
    }

    return odict


def AGD(
    vel,
    data,
    errors,
    alpha1=None,
    alpha2=None,
    # plot=False,
    mode="python",
    verbose=False,
    SNR_thresh=5.0,
    BLFrac=0.1,
    SNR2_thresh=5.0,
    deblend=True,
    perform_final_fit=True,
    phase="one",
):
    """ Autonomous Gaussian Decomposition
    """

    if type(SNR2_thresh) != type([]):
        SNR2_thresh = [SNR2_thresh, SNR2_thresh]
    if type(SNR_thresh) != type([]):
        SNR_thresh = [SNR_thresh, SNR_thresh]

    say("\n  --> AGD() \n", verbose)

    if (not alpha2) and (phase == "two"):
        print("alpha2 value required")
        return

    # print(vel)
    dv = np.abs(vel[1] - vel[0])
    v_to_i = interp1d(vel, np.arange(len(vel)))

    # --------------------------------------#
    # Find phase-one guesses               #
    # --------------------------------------#
    agd1 = initialGuess(
        vel,
        data,
        errors=None,
        alpha=alpha1,
        # plot=plot,
        mode=mode,
        verbose=verbose,
        SNR_thresh=SNR_thresh[0],
        BLFrac=BLFrac,
        SNR2_thresh=SNR2_thresh[0],
        deblend=deblend,
    )

    amps_g1, widths_g1, offsets_g1, u2 = (
        agd1["amps"],
        agd1["FWHMs"],
        agd1["means"],
        agd1["u2"],
    )
    params_g1 = np.append(np.append(amps_g1, widths_g1), offsets_g1)
    ncomps_g1 = len(params_g1) // 3
    ncomps_g2 = 0  # Default
    ncomps_f1 = 0  # Default

    # ----------------------------#
    # Find phase-two guesses #
    # ----------------------------#
    if phase == "two":
        say("Beginning phase-two AGD... ", verbose)
        ncomps_g2 = 0

        # ----------------------------------------------------------#
        # Produce the residual signal                               #
        #  -- Either the original data, or intermediate subtraction #
        # ----------------------------------------------------------#
        if ncomps_g1 == 0:
            say(
                "Phase 2 with no narrow comps -> No intermediate subtration... ",
                verbose,
            )
            residuals = data
        else:
            # "Else" Narrow components were found, and Phase == 2, so perform intermediate subtraction...

            # The "fitmask" is a collection of windows around the a list of phase-one components
            fitmask, fitmaskw = create_fitmask(
                len(vel), v_to_i(offsets_g1), widths_g1 / dv / 2.355 * 0.9
            )
            notfitmask = 1 - fitmask

            # Error function for intermediate optimization
            def objectiveD2_leastsq(paramslm):
                params = vals_vec_from_lmfit(paramslm)
                model0 = func(vel, *params)
                model2 = np.diff(np.diff(model0.ravel())) / dv / dv
                resids1 = fitmask[1:-1] * (model2 - u2[1:-1]) / errors[1:-1]
                resids2 = notfitmask * (model0 - data) #/ errors / 10.0
                return resids2
                # return np.append(resids1, resids2)

            # Perform the intermediate fit using LMFIT
            t0 = time.time()
            say("Running LMFIT on initial narrow components...", verbose)
            lmfit_params = paramvec_to_lmfit(params_g1)
            result = lmfit_minimize(objectiveD2_leastsq, lmfit_params, method="least_squares")
            # result = lmfit_minimize(objectiveD2_leastsq, lmfit_params, method="leastsq")
            params_f1 = vals_vec_from_lmfit(result.params)
            ncomps_f1 = len(params_f1) // 3

            # # Make "FWHMS" positive
            # params_f1[0:ncomps_f1][params_f1[0:ncomps_f1] < 0.0] = (
            #     -1 * params_f1[0:ncomps_f1][params_f1[0:ncomps_f1] < 0.0]
            # )

            del lmfit_params
            say("LMFIT fit took {0} seconds.".format(time.time() - t0))

            if result.success:
                # Compute intermediate residuals
                # Median filter on 2x effective scale to remove poor subtractions of strong components
                intermediate_model = func(
                    vel, *params_f1
                ).ravel()  # Explicit final (narrow) model
                median_window = 2.0 * 10 ** ((np.log10(alpha1) + 2.187) / 3.859)
                residuals = median_filter(
                    data - intermediate_model, np.int(median_window)
                )
            else:
                residuals = data
            # Finished producing residual signal # ---------------------------

        # Search for phase-two guesses
        agd2 = initialGuess(
            vel,
            residuals,
            errors=None,
            alpha=alpha2,
            mode=mode,
            verbose=verbose,
            SNR_thresh=SNR_thresh[1],
            BLFrac=BLFrac,
            SNR2_thresh=SNR2_thresh[1],  # June 9 2014, change
            deblend=deblend,
            # plot=plot,
        )
        ncomps_g2 = agd2["N_components"]
        if ncomps_g2 > 0:
            params_g2 = np.concatenate([agd2["amps"], agd2["FWHMs"], agd2["means"]])
        else:
            params_g2 = []
        u22 = agd2["u2"]

        # END PHASE 2 <<<

    # Check for phase two components, make final guess list
    # ------------------------------------------------------
    if phase == "two" and (ncomps_g2 > 0):
        amps_gf = np.append(params_g1[0:ncomps_g1], params_g2[0:ncomps_g2])
        widths_gf = np.append(
            params_g1[ncomps_g1: 2 * ncomps_g1], params_g2[ncomps_g2: 2 * ncomps_g2]
        )
        offsets_gf = np.append(
            params_g1[2 * ncomps_g1: 3 * ncomps_g1],
            params_g2[2 * ncomps_g2: 3 * ncomps_g2],
        )
        params_gf = np.concatenate([amps_gf, widths_gf, offsets_gf])
        ncomps_gf = len(params_gf) // 3
    else:
        params_gf = params_g1
        ncomps_gf = len(params_gf) // 3

    # Sort final guess list by amplitude
    # ----------------------------------
    say("N final parameter guesses: " + str(ncomps_gf))
    amps_temp = params_gf[0:ncomps_gf]
    widths_temp = params_gf[ncomps_gf: 2 * ncomps_gf]
    offsets_temp = params_gf[2 * ncomps_gf: 3 * ncomps_gf]
    w_sort_amp = np.argsort(amps_temp)[::-1]
    params_gf = np.concatenate(
        [amps_temp[w_sort_amp], widths_temp[w_sort_amp], offsets_temp[w_sort_amp]]
    )

    # print(params_gf)
    if perform_final_fit:
        say("\n\n  --> Final Fitting... \n", verbose)

        if ncomps_gf > 0:
            # Objective functions for final fit
            def objective_leastsq(paramslm):
                params = vals_vec_from_lmfit(paramslm)
                resids = (func(vel, *params).ravel() - data.ravel()) / errors
                return resids

            # Final fit using unconstrained parameters
            t0 = time.time()
            lmfit_params = paramvec_to_lmfit(params_gf)
            # result2 = lmfit_minimize(objective_leastsq, lmfit_params, method="differential_evolution")
            result2 = lmfit_minimize(objective_leastsq, lmfit_params, method="least_squares")
            params_fit = vals_vec_from_lmfit(result2.params)
            params_errs = errs_vec_from_lmfit(result2.params)
            ncomps_fit = len(params_fit) // 3

            del lmfit_params
            say("Final fit took {0} seconds.".format(time.time() - t0), verbose)

        # # Make "FWHMS" positive
        # params_fit[0:ncomps_fit][params_fit[0:ncomps_fit] < 0.0] = (
        #     -1 * params_fit[0:ncomps_fit][params_fit[0:ncomps_fit] < 0.0]
        # )

            best_fit_final = func(vel, *params_fit).ravel()
            rchi2 = np.sum((data - best_fit_final) ** 2 / errors ** 2) / len(data)

            # Check if any amplitudes are identically zero, if so, remove them.
            if np.any(params_fit[0:ncomps_gf] == 0):
                amps_fit = params_fit[0:ncomps_gf]
                fwhms_fit = params_fit[ncomps_gf: 2 * ncomps_gf]
                offsets_fit = params_fit[2 * ncomps_gf: 3 * ncomps_gf]
                w_keep = amps_fit > 0.0
                params_fit = np.concatenate(
                    [amps_fit[w_keep], fwhms_fit[w_keep], offsets_fit[w_keep]]
                )
                ncomps_fit = len(params_fit) // 3
        else:
            best_fit_final = np.zeros(len(vel))
            rchi2 = -999.
            ncomps_fit = ncomps_gf

    # if plot:
    #     #                       P L O T T I N G
    #     datamax = np.max(data)
    #
    #     # Set up figure
    #     fig = plt.figure("AGD results", [12, 12])
    #     ax1 = fig.add_axes([0.1, 0.5, 0.4, 0.4])  # Initial guesses (alpha1)
    #     ax2 = fig.add_axes([0.5, 0.5, 0.4, 0.4])  # D2 fit to peaks(alpha2)
    #     ax3 = fig.add_axes([0.1, 0.1, 0.4, 0.4])  # Initial guesses (alpha2)
    #     ax4 = fig.add_axes([0.5, 0.1, 0.4, 0.4])  # Final fit
    #
    #     # Decorations
    #     plt.figtext(0.52, 0.47, "Final fit")
    #     # if perform_final_fit:
    #     #     plt.figtext(0.52, 0.45, "Reduced Chi2: {0:3.1f}".format(rchi2))
    #     #     plt.figtext(0.52, 0.43, "N components: {0}".format(ncomps_fit))
    #
    #     plt.figtext(0.12, 0.47, "Phase-two initial guess")
    #     plt.figtext(0.12, 0.45, "N components: {0}".format(ncomps_g2))
    #
    #     plt.figtext(0.12, 0.87, "Phase-one initial guess")
    #     plt.figtext(0.12, 0.85, "N components: {0}".format(ncomps_g1))
    #
    #     plt.figtext(0.52, 0.87, "Intermediate fit")
    #
    #     # Initial Guesses (Panel 1)
    #     # -------------------------
    #     ax1.xaxis.tick_top()
    #     u2_scale = 1.0 / np.max(np.abs(u2)) * datamax * 0.5
    #     ax1.plot(vel, data, "-k")
    #     ax1.plot(vel, u2 * u2_scale, "-r")
    #     ax1.plot(vel, vel / vel * agd1["thresh"], "-k")
    #     ax1.plot(vel, vel / vel * agd1["thresh2"] * u2_scale, "--r")
    #
    #     for i in range(ncomps_g1):
    #         one_component = gaussian(
    #             params_g1[i], params_g1[i + ncomps_g1], params_g1[i + 2 * ncomps_g1]
    #         )(vel)
    #         ax1.plot(vel, one_component, "-g")
    #
    #     # Plot intermediate fit components (Panel 2)
    #     # ------------------------------------------
    #     ax2.xaxis.tick_top()
    #     ax2.plot(vel, data, "-k")
    #     ax2.yaxis.tick_right()
    #     for i in range(ncomps_f1):
    #         one_component = gaussian(
    #             params_f1[i], params_f1[i + ncomps_f1], params_f1[i + 2 * ncomps_f1]
    #         )(vel)
    #         ax2.plot(vel, one_component, "-", color="blue")
    #
    #     # Residual spectrum (Panel 3)
    #     # -----------------------------
    #     if phase == "two":
    #         u22_scale = 1.0 / np.abs(u22).max() * np.max(residuals) * 0.5
    #         ax3.plot(vel, residuals, "-k")
    #         ax3.plot(vel, vel / vel * agd2["thresh"], "--k")
    #         ax3.plot(vel, vel / vel * agd2["thresh2"] * u22_scale, "--r")
    #         ax3.plot(vel, u22 * u22_scale, "-r")
    #         for i in range(ncomps_g2):
    #             one_component = gaussian(
    #                 params_g2[i], params_g2[i + ncomps_g2], params_g2[i + 2 * ncomps_g2]
    #             )(vel)
    #             ax3.plot(vel, one_component, "-g")
    #
    #     # Plot best-fit model (Panel 4)
    #     # -----------------------------
    #     if perform_final_fit:
    #         ax4.yaxis.tick_right()
    #         ax4.plot(vel, best_fit_final, label="final model", color="purple")
    #         ax4.plot(vel, data, label="data", color="black")
    #         for i in range(ncomps_fit):
    #             one_component = gaussian(
    #                 params_fit[i],
    #                 params_fit[i + ncomps_fit],
    #                 params_fit[i + 2 * ncomps_fit],
    #             )(vel)
    #             ax4.plot(vel, one_component, "-", color="purple")
    #         ax4.plot(vel, best_fit_final, "-", color="purple")
    #
    #     plt.show()
    #     plt.close()

    # Construct output dictionary (odict)
    # -----------------------------------
    odict = {}
    odict["initial_parameters"] = params_gf
    odict["N_components"] = ncomps_gf

    if (perform_final_fit) and (ncomps_gf > 0):
        odict["best_fit_parameters"] = params_fit
        odict["best_fit_errors"] = params_errs
        odict["rchi2"] = rchi2

    return (1, odict)
