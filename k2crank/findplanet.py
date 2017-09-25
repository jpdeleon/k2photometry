import numpy as np
import matplotlib.pyplot as pl
import gatspy
from os.path import exists, join

from gatspy.periodic import LombScargleFast

#from model_transits import *
from auxiliaries import *

import bls


def plot_raw_lc(t,f,outputfolder='',starname=''):
    fig, ax = pl.subplots(1,1,figsize=(15,3))
    ax.plot(t, f, '.')
    ax.set_ylabel('Flux')
    ax.set_xlabel('Time (day)')
    ax.set_title('working lc for planet finding: {}'.format(starname))
    pl.savefig(join(outputfolder, 'working_lc_' + str(starname) + '.png'))


def find_period(t,f,showfig=True,outputfolder='',starname=''):
    model = LombScargleFast().fit(t, f)
    periods, power = model.periodogram_auto(nyquist_factor=100)
    idx1 = periods > 1
    if showfig:
        idx2 = np.argmax(power[idx1])
        period = periods[idx1][idx2]

        fig, ax = pl.subplots(1,1,figsize=(15,5))
        ax.plot(periods, power, 'k-')
        ax.set(xlim=(0.5, 5),
        #         , ylim=(0, 0.01),
           xlabel='period (days)',
           ylabel='Lomb-Scargle Power')
        ax.vlines(period, *ax.get_ylim(), linestyles='dotted', colors='r')
        ax.set_title('best period: {0:.3f}'.format(period))
    pl.savefig(join(outputfolder, 'LombScargle_' + str(starname) + '.png'))
    return period


def estimate_k(t,f,p,showfig=False):
    '''
    k=Rp/Rs estimate transit depth assumed to be within 0.01 percentile
    '''
    baseline,minimum=np.percentile(f[np.array(t%p).argsort()], [50,1])
    if showfig:
        pl.hist(f[np.array(t%p).argsort()]);
    #print(baseline,minimum)
    return np.sqrt(baseline-minimum)


def estimate_t0(t,f,tlower=None,tupper=None, showfig=False,outputfolder='',starname=''):
    '''
    very basic search for t0 given interval tlower and tupper
    '''
    if tlower is None and tupper is None:
        tlower, tupper=t[0],t[200]
    idx = (t > tlower) & (t < tupper)
    tsub, fsub = t[idx], f[idx]
    idx = fsub < np.median(fsub) - 0.5 * np.nanstd(fsub)
    t0 = np.median(tsub[idx])
    if showfig:
        fig, ax = pl.subplots(1,1,figsize=(15,3))
        ax.plot(tsub, fsub, '.')
        ax.set_title(starname)
        ax.vlines(t0, *ax.get_ylim())
    return t0

def impact_param(a,Rstar):
    '''
    a is semi-major axis, not scaled_a = R_star/a
    '''
    return a * np.cos(i)/Rstar

def get_tns(t, p, t0):
    '''
    determine transit conjuctions
    '''

    idx = t != 0
    t = t[idx]

    while t0-p > t.min():
        t0 -= p
    if t0 < t.min():
        t0 += p

    tns = [t0+p*i for i in range(int((t.max()-t0)/p+1))]

    while tns[-1] > t.max():
        tns.pop()

    while tns[0] < t.min():
        tns = tns[1:]

    return tns


def fold(t, f, p, t0, width=0.4, clip=False, bl=False, t14=0.1):
    '''
    fold lc; very sensitive to p & t0
    '''
    tns = get_tns(t, p, t0)
    tf, ff = np.empty(0), np.empty(0)
    for i,tn in enumerate(tns):
        idx = (t > tn - width/2.) & (t < tn + width/2.)
        ti = t[idx]-tn
        fi = f[idx]
        fi /= np.nanmedian(fi)
        if bl:
            idx = (ti < -t14/2.) | (ti > t14/2.)
            assert np.isfinite(ti[idx]).all() & np.isfinite(fi[idx]).all()
            assert idx.sum() > 0
            try:
                res = sm.RLM(fi[idx], sm.add_constant(ti[idx])).fit()
                if np.abs(res.params[1]) > 1e-2:
                    print('bad data probably causing poor fit')
                    print('transit {} baseline params: {}'.format(i, res.params))
                    continue
                model = res.params[0] + res.params[1] * ti
                fi = fi - model + 1
            except:
                print("error computing baseline for transit {}".format(i))
                print("num. points: {}".format(idx.sum()))
                print(ti)
        tf = np.append(tf, ti)
        ff = np.append(ff, fi / np.nanmedian(fi))
    idx = np.argsort(tf)
    tf = tf[idx]
    ff = ff[idx]
    if clip:
        fc = sigma_clip(ff, sigma_lower=10, sigma_upper=2)
        tf, ff = tf[~fc.mask], ff[~fc.mask]
    return tf, ff


def fold_data(t,y,period):
    '''
    alternative to fold function above
    '''
    # simple module to fold data based on period
    folded = t % period
    inds = np.array(folded).argsort()
    t_folded = folded[inds]
    y_folded = y[inds]

    return t_folded,y_folded


def plot_tns(tns,t,f, f1=0.975, f2=0.98,outputfolder='',starname=''):
    fig, ax = pl.subplots(1,1,figsize=(15,5))
    ax.plot(t, f, '.')
    ax.vlines(tns, f1,f2)
    ax.set_title(starname)
    pl.savefig(join(outputfolder, 'tns_' + str(starname) + '.png'))


def plot_folded_lc(t,f,period,t0,outputfolder='',starname=''):
    tf, ff = fold(t, f, period, t0)

    fig, ax = pl.subplots(1,1,figsize=(15,5))
    ax.plot(tf, ff, '.')
    ax.set_title('Phase-folded lc before optimization'.format(starname))
    pl.savefig(join(outputfolder, 'folded_lc_' + str(starname) + '.png'))


def estimate_t14(value=0.01):
    if value:
        return value

######################################
from pytransit import MandelAgol

def model_t(theta, t):
    MA = MandelAgol()
    k,t0,p,a,i,u1,u2,_,_,_,_,_ = theta
    model = MA.evaluate(t, k, (u1,u2), t0, p, a, i)

    return model


def baseline(theta, t):
    ti = t - t.mean()
    c0,c1,c2,c3 = theta[-4:]
    return c0 + c1 * ti + c2 * ti**2 + c3 * ti**3


def lnlike(theta, t, f):
    k,t0,p,a,i,u1,u2,sig,c0,c1,c2,c3 = theta
    m = model_t(theta, t) + baseline(theta, t)
    resid = f - m
    inv_sigma2 = 1.0/(sig**2)

    return -0.5*(np.sum((resid)**2*inv_sigma2 - np.log(inv_sigma2)))


def lnprob(theta, t, f):
    #prior
    if np.any(theta[:-4] < 0):
        return -np.inf
    if theta[4] > np.pi/2.:
        return -np.inf
    #loglike
    ll = lnlike(theta, t, f)
    return ll if np.isfinite(ll) else -np.inf


def scaled_a(p, t14, k, i=np.pi/2.):
    numer = np.sqrt( (k + 1) ** 2 )
    denom = np.sin(i) * np.sin(t14 * np.pi / p)
    return float(numer / denom)

def compute_a(a_scaled,Rstar):
    return Rstar/a_scaled

import scipy.optimize as op

def fit_folded_lc(initial, args, method='powell',verbose=True):

    nlp = lambda *args: -lnprob(*args)

    opt = op.minimize(nlp, initial, args=args, method=method)
    labels='k,t0,p,a,i,u1,u2,sig,c0,c1,c2,c3'.split(',')

    if verbose:
        print('converged: {}'.format(opt.success))
        for i,j in zip(labels,opt.x):
            print('{0}: {1}'.format(i,j))
    return opt


def plot_fit(theta,t,f,show_model=True,outputfolder='',starname=''):
    t0, p = theta[1], theta[2]

    tf, ff = fold(t, f, p, t0)
    #ff /= np.median(ff)

    fig, ax = pl.subplots(1,1,figsize=(15,5))
    ax.plot(tf, ff, '.', label='data')
    ax.set_xlabel('Phase')
    ax.set_ylabel('Normalized Flux')
    fmod=model_t(theta, t)
    ttmod,ffmod=fold(t,fmod,p,t0)
    ax.plot(ttmod,ffmod,'r.-',label='model')
    ax.set_title('Phase-folded with model fit (MLE): {}'.format(starname))
    ax.legend()
    pl.savefig(join(outputfolder, 'folded_model_optimized_fit' + str(starname) + '.png'))
