## The standard DGLM forecast functions
import numpy as np
from scipy import stats
from scipy.special import gamma

def forecast_aR(mod, k):
    Gk = np.linalg.matrix_power(mod.G, k - 1)
    a = Gk @ mod.a
    R = Gk @ mod.R @ Gk.T
    if mod.discount_forecast:
        R += (k - 1) * mod.W
    return a, R

def forecast_marginal(mod, k, X = None, nsamps = 1, mean_only = False, state_mean_var = False):
    """
    Forecast function k steps ahead (marginal)
    """
    # Plug in the correct F values
    F = np.copy(mod.F)
    if mod.nregn > 0:
        F[mod.iregn] = X.reshape(mod.nregn,1)
        
    # Evolve to the prior for time t + k
    a, R = forecast_aR(mod, k)

    # Mean and variance
    ft, qt = mod.get_mean_and_var(F, a, R)

    if state_mean_var:
        return ft, qt
        
    # Choose conjugate prior, match mean and variance
    param1, param2 = mod.get_conjugate_params(ft, qt, mod.param1, mod.param2)
    
    if mean_only:
        return mod.get_mean(param1, param2)
        
    # Simulate from the forecast distribution
    return mod.simulate(param1, param2, nsamps)


def forecast_path(mod, k, X = None, nsamps = 1):
    """
    Forecast function for the k-step path
    k: steps ahead to forecast
    X: array with k rows for the future regression components
    nsamps: Number of samples to draw from forecast distribution
    """
        
    samps = np.zeros([nsamps, k])
        
    F = np.copy(mod.F)
        
    for n in range(nsamps):
        param1 = mod.param1
        param2 = mod.param2
        
        a = np.copy(mod.a)
        R = np.copy(mod.R)
                
        for i in range(k):

            # Plug in the correct F values
            if mod.nregn > 0:
                F[mod.iregn] = X[i,:].reshape(mod.nregn,1)

            # Get mean and variance
            ft, qt = mod.get_mean_and_var(F, a, R)

            # Choose conjugate prior, match mean and variance
            param1, param2 = mod.get_conjugate_params(ft, qt, param1, param2)

            # Simulate next observation
            samps[n, i] = mod.simulate(param1, param2, nsamps = 1)

            # Update based on that observation
            param1, param2, ft_star, qt_star = mod.update_conjugate_params(samps[n, i], param1, param2)

            # Kalman filter update on the state vector (using Linear Bayes approximation)
            m = a + R @ F * (ft_star - ft)/qt
            C = R - R @ F @ F.T @ R * (1 - qt_star/qt)/qt
            
            # Get priors a, R for the next time step
            a = mod.G @ m
            R = mod.G @ C @ mod.G.T
            R = (R + R.T)/2
                
            # Discount information
            if mod.discount_forecast:
                R = R + mod.W

    return samps


def forecast_path_approx(mod, k, X = None, nsamps = 1, t_dist=False, y=None, nu=9):
    """
    Forecast function for the k-step path
    k: steps ahead to forecast
    X: array with k rows for the future regression components
    nsamps: Number of samples to draw from forecast distribution
    """
    
    lambda_mu = np.zeros([k])
    lambda_cov = np.zeros([k, k])
    
    F = np.copy(mod.F)
                        
    Flist = [None for x in range(k)]
    Rlist = [None for x in range(k)]
    
    for i in range(k):

        # Evolve to the prior at time t + i + 1
        a, R = forecast_aR(mod, i+1)

        Rlist[i] = R

        # Plug in the correct F values
        if mod.nregn > 0:
            F[mod.iregn] = X[i,:].reshape(mod.nregn,1)
            
        Flist[i] = np.copy(F)
            
        # Find lambda mean and var
        ft, qt = mod.get_mean_and_var(F, a, R)
        lambda_mu[i] = ft
        lambda_cov[i,i] = qt
        
        # Find covariances with previous lambda values
        for j in range(i):
            # Covariance matrix between the state vector at times j, i, i > j
            cov_ij = np.linalg.matrix_power(mod.G, i-j) @ Rlist[j]
            # Covariance between lambda at times j, i
            lambda_cov[j,i] = lambda_cov[i,j] = Flist[j].T @ cov_ij @ Flist[i]

    if y is not None:
        return forecast_path_approx_dens_MC(mod, y, lambda_mu, lambda_cov, t_dist, nu, nsamps)
    else:
        return forecast_path_approx_sim(mod, k, lambda_mu, lambda_cov, nsamps, t_dist, nu)


def forecast_marginal_bindglm(mod, n, k, X=None, nsamps=1, mean_only=False):
    """
    Forecast function k steps ahead (marginal)
    """
    # Plug in the correct F values
    F = np.copy(mod.F)
    if mod.nregn > 0:
        F[mod.iregn] = X.reshape(mod.nregn,1)

    # Evolve to the prior for time t + k
    a, R = forecast_aR(mod, k)

    # Mean and variance
    ft, qt = mod.get_mean_and_var(F, a, R)

    # Choose conjugate prior, match mean and variance
    param1, param2 = mod.get_conjugate_params(ft, qt, mod.param1, mod.param2)

    if mean_only:
        return mod.get_mean(n, param1, param2)

    # Simulate from the forecast distribution
    return mod.simulate(n, param1, param2, nsamps)

def forecast_path_normaldlm(mod, k, X = None, nsamps = 1, multiscale=False, AR=False):

    samps = np.zeros([nsamps, k])
    F = np.copy(mod.F)

    ## Initialize samples of the state vector and variance from the prior
    v = 1.0 / np.random.gamma(shape = mod.n/2, scale = 2/(mod.n * mod.s[0]), size = nsamps)
    thetas = list(map(lambda var: np.random.multivariate_normal(mean = mod.a.reshape(-1), cov = var/mod.s * mod.R, size = 1).T,
                     v))

    for i in range(k):
        # Plug in the correct F values
        if mod.nregn > 0:
            F[mod.iregn] = X[i, :].reshape(mod.nregn,1)

        # mean
        ft = np.array(list(map(lambda theta: F.T @ theta,
                        thetas))).reshape(-1)

        # Simulate from the sampling model
        samps[:,i] = mod.simulate_from_sampling_model(ft, v, nsamps)

        # Evolve the state vector and variance for the next timestep
        v = v * np.random.beta(mod.delVar*mod.n/2, ((1-mod.delVar)*mod.n)/2, size=nsamps)
        thetas = list(
            map(lambda theta, var: theta + np.random.multivariate_normal(mean = np.zeros(theta.shape[0]), cov=var / mod.s * mod.W, size=1).T,
                thetas, v))

    return samps


def forecast_path_approx_sim(mod, k, lambda_mu, lambda_cov, nsamps, t_dist = False, nu = 9):
    """
    lambda_mu: kx1 Mean vector for forecast mean over t+1:t+k
    lambda_cov: kxk Covariance matrix for the forecast over t+1:t+k
    """
        
    if t_dist:
        #nu = 8
        scale = lambda_cov * ((nu - 2) / nu)
        joint_samps = multivariate_t(lambda_mu, scale, nu, nsamps).T
        genlist = list(map(lambda f, q: stats.t(loc = f, scale = np.sqrt(q), df = nu),
                      lambda_mu, np.diag(scale)))
    else:
        # Simulate from a joint multivariate normal with lambda_mu, lambda_cov
        joint_samps = np.random.multivariate_normal(lambda_mu, lambda_cov, size=nsamps).T
        genlist = list(map(lambda f, q: stats.norm(f, np.sqrt(q)),
                      lambda_mu, np.diag(lambda_cov)))
    
    # Find the marginal conjugate parameters
    conj_params = list(map(lambda f, q: mod.get_conjugate_params(f, q, mod.param1, mod.param2),
                           lambda_mu, np.diag(lambda_cov)))
    
    # Use the marginal CDF of the joint distribution to convert our samples into uniform RVs
    unif_rvs = list(map(lambda gen, samps: gen.cdf(samps),
              genlist, joint_samps))
    
    # Use inverse-CDF along each margin to get implied PRIOR value (e.g. a gamma dist RV for a poisson sampling model)
    priorlist = list(map(lambda params, unif_rv: mod.prior_inverse_cdf(unif_rv, params[0], params[1]),
                    conj_params, unif_rvs))
    
    # Simulate from the sampling model (e.g. poisson)
    return np.array(list(map(lambda prior: mod.simulate_from_sampling_model(prior, nsamps),
            priorlist))).T

def forecast_path_approx_dens_MC(mod, y, lambda_mu, lambda_cov, t_dist=False, nu = 9, nsamps = 500):
    """
    lambda_mu: kx1 Mean vector for forecast mean over t+1:t+k
    lambda_cov: kxk Covariance matrix for the forecast over t+1:t+k
    """
    not_missing = np.logical_not(np.isnan(y))
    y = y[not_missing]
    lambda_mu = lambda_mu[not_missing]
    lambda_cov = lambda_cov[np.ix_(not_missing, not_missing)]

    # Get the marginals of the multivariate distribution
    if t_dist:
        scale = lambda_cov * ((nu - 2) / nu)
        joint_samps = multivariate_t(lambda_mu, scale, nu, nsamps).T
        genlist = list(map(lambda f, q: stats.t(loc=f, scale=np.sqrt(q), df=nu),
                           lambda_mu, np.diag(scale)))
    else:
        joint_samps = np.random.multivariate_normal(lambda_mu, lambda_cov, size=nsamps).T
        genlist = list(map(lambda f, q: stats.norm(f, np.sqrt(q)),
                           lambda_mu, np.diag(lambda_cov)))

    # Find the marginal distribution conjugate parameters
    conj_params = list(map(lambda f, q: mod.get_conjugate_params(f, q, mod.param1, mod.param2),
                           lambda_mu, np.diag(lambda_cov)))

    # Use the marginal CDF of the joint distribution to convert our samples into uniform RVs
    unif_rvs = list(map(lambda gen, samps: gen.cdf(samps),
                       genlist, joint_samps))

    # Use inverse-CDF along each margin to get implied PRIOR value (e.g. a gamma dist RV for a poisson sampling model)
    priorlist = list(map(lambda params, cdf: mod.prior_inverse_cdf(cdf, params[0], params[1]),
                         conj_params, unif_rvs))

    # Get the density of the y values, using Monte Carlo integration (i.e. an average over the samples)
    density_list = list(map(lambda y, prior: mod.sampling_density(y, prior),
                            y, priorlist))

    # Get the product of the densities to get the path density (they are independent, conditional upon the prior value at each time t+k)
    path_density_list = list(map(lambda dens: np.exp(np.sum(np.log(dens))),
                                 zip(*density_list)))

    # Return their average, on the log scale
    return np.log(np.mean(path_density_list))


def forecast_joint_approx_sim(mod_list, lambda_mu, lambda_cov, nsamps, t_dist=False, nu=9):
    """
    lambda_mu: kx1 Mean vector for forecast mean over t+1:t+k
    lambda_cov: kxk Covariance matrix for the forecast over t+1:t+k
    """

    if t_dist:
        # nu = 8
        scale = lambda_cov * ((nu - 2) / nu)
        joint_samps = multivariate_t(lambda_mu, scale, nu, nsamps).T
        genlist = list(map(lambda f, q: stats.t(loc=f, scale=np.sqrt(q), df=nu),
                           lambda_mu, np.diag(scale)))
    else:
        # Simulate from a joint multivariate normal with lambda_mu, lambda_cov
        joint_samps = np.random.multivariate_normal(lambda_mu, lambda_cov, size=nsamps).T
        genlist = list(map(lambda f, q: stats.norm(f, np.sqrt(q)),
                           lambda_mu, np.diag(lambda_cov)))

    # Find the marginal conjugate parameters
    conj_params = []
    for i, mod in enumerate(mod_list):
        conj_params.append(mod.get_conjugate_params(lambda_mu[i], lambda_cov[i, i], mod.param1, mod.param2))

    # Use the marginal CDF of the joint distribution to convert our samples into uniform RVs
    unif_rvs = list(map(lambda gen, samps: gen.cdf(samps),
                        genlist, joint_samps))

    # Use inverse-CDF along each margin to get implied PRIOR value (e.g. a gamma dist RV for a poisson sampling model)
    priorlist = list(map(lambda params, unif_rv: mod.prior_inverse_cdf(unif_rv, params[0], params[1]),
                         conj_params, unif_rvs))

    # Simulate from the sampling model (e.g. poisson)
    return np.array(list(map(lambda prior: mod.simulate_from_sampling_model(prior, nsamps),
                             priorlist))).T

def forecast_joint_approx_dens_MC(mod_list, y, lambda_mu, lambda_cov, t_dist=False, nu = 9, nsamps = 500):
    """
    lambda_mu: kx1 Mean vector for forecast mean over t+1:t+k
    lambda_cov: kxk Covariance matrix for the forecast over t+1:t+k
    """
    not_missing = np.logical_not(np.isnan(y))
    y = y[not_missing]
    lambda_mu = lambda_mu[not_missing]
    lambda_cov = lambda_cov[np.ix_(not_missing, not_missing)]

    # Get the marginals of the multivariate distribution
    if t_dist:
        scale = lambda_cov * ((nu - 2) / nu)
        joint_samps = multivariate_t(lambda_mu, scale, nu, nsamps).T
        genlist = list(map(lambda f, q: stats.t(loc=f, scale=np.sqrt(q), df=nu),
                           lambda_mu, np.diag(scale)))
    else:
        joint_samps = np.random.multivariate_normal(lambda_mu, lambda_cov, size=nsamps).T
        genlist = list(map(lambda f, q: stats.norm(f, np.sqrt(q)),
                           lambda_mu, np.diag(lambda_cov)))

    # Find the marginal distribution conjugate parameters
    conj_params = []
    for i, mod in enumerate(mod_list):
        conj_params.append(mod.get_conjugate_params(lambda_mu[i], lambda_cov[i, i], mod.param1, mod.param2))

    # Use the marginal CDF of the joint distribution to convert our samples into uniform RVs
    unif_rvs = list(map(lambda gen, samps: gen.cdf(samps),
                       genlist, joint_samps))

    # Use inverse-CDF along each margin to get implied PRIOR value (e.g. a gamma dist RV for a poisson sampling model)
    priorlist = list(map(lambda params, cdf: mod.prior_inverse_cdf(cdf, params[0], params[1]),
                         conj_params, unif_rvs))

    # Get the density of the y values, using Monte Carlo integration (i.e. an average over the samples)
    density_list = list(map(lambda y, prior: mod.sampling_density(y, prior),
                            y, priorlist))

    # Get the product of the densities to get the joint density (they are independent, conditional upon the prior value at each time t+k)
    joint_density_list = list(map(lambda dens: np.exp(np.sum(np.log(dens))),
                                 zip(*density_list)))

    # Return their average, on the log scale
    return np.log(np.mean(joint_density_list))

def multivariate_t(mean, scale, nu, nsamps):
    '''
    mean = mean
    scale = covariance matrix * ((nu-2)/nu)
    nu = degrees of freedom
    nsamps = # of samples to produce
    '''
    p = len(mean)
    g = np.tile(np.random.gamma(nu/2.,2./nu, nsamps), (p, 1)).T
    Z = np.random.multivariate_normal(np.zeros(p), scale, nsamps)
    return mean + Z/np.sqrt(g)

def multivariate_t_density(y, mean, scale, nu):
    '''
    y = vector of observations
    mean = mean
    scale = covariance matrix * ((nu-2)/nu)
    nu = degrees of freedom
    '''
    y = y.reshape(-1, 1)
    mean = mean.reshape(-1, 1)
    dim = len(y)
    if dim > 1:
        constant = gamma((nu + dim) / 2) / (gamma(nu / 2) * np.sqrt((np.pi * nu) ** dim * np.linalg.det(scale)))
        dens = (1. + ((y - mean).T @ np.linalg.inv(scale) @ (y - mean)) / nu) ** (-(nu + dim) / 2)
    else:
        constant = gamma((nu + dim) / 2) / (gamma(nu / 2) * np.sqrt((np.pi * nu) ** dim * scale))
        dens = (1. + ((y - mean))**2 / (nu * scale)) ** (-(nu + dim) / 2)

    return 1. * constant * dens

def forecast_state_mean_and_var(mod, k = 1, X = None):
    """
       Forecast function that returns the mean and variance of lambda = state vector * predictors
       """
    # Plug in the correct F values
    F = np.copy(mod.F)
    if mod.nregn > 0:
        F[mod.iregn] = X.reshape(mod.nregn, 1)

    # Evolve to the prior for time t + k
    a, R = forecast_aR(mod, k)

    # Mean and variance
    ft, qt = mod.get_mean_and_var(F, a, R)

    return ft, qt

def forecast_marginal_dens_MC(mod, k, X = None, nsamps = 1, y = None):
    """
    Function to get marginal forecast density (marginal)
    """
    # Plug in the correct F values
    F = np.copy(mod.F)
    if mod.nregn > 0:
        F[mod.iregn] = X.reshape(mod.nregn, 1)

    # Evolve to the prior for time t + k
    a, R = forecast_aR(mod, k)

    # Mean and variance
    ft, qt = mod.get_mean_and_var(F, a, R)

    # Choose conjugate prior, match mean and variance
    param1, param2 = mod.get_conjugate_params(ft, qt, mod.param1, mod.param2)

    # Simulate from the conjugate prior
    prior_samps = mod.simulate_from_prior(param1, param2, nsamps)

    # Get the densities
    densities = mod.sampling_density(y, prior_samps)

    # Take a Monte Carlo average, and return the mean density, on the log scale
    return np.log(np.mean(densities))

