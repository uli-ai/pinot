""" Combine representation, parameterization, and distribution class
to construct a model.

"""
# =============================================================================
# IMPORTS
# =============================================================================
import dgl
import torch

# =============================================================================
# MODULE FUNCTIONS
# =============================================================================


class Net(torch.nn.Module):
    """ An object that combines the representation and parameter
    learning, puts into a predicted distribution and calculates the
    corresponding divergence.


    Attributes
    ----------
    representation: a `pinot.representation` module
        the model that translates graphs to latent representations
    output_regression: a `torch.nn.Module` or None,
        if None, this will be set as a simple `Linear` layer that inputs
        the latent dimension and output the number of parameters for
        `self.distribution_class`
    noise_model: either a string (
        one of 
            'normal-homoschedastic',
            'normal-heteroschedastic',
            'normal-homoschedastic-fixed') 
        or a function that transforms a set of parameters.


    """

    def __init__(
        self,
        representation,
        output_regression=None,
        measurement_dimension=1,
        noise_model='normal-heteroschedastic',
    ):
        
        super(Net, self).__init__()
        self.representation = representation

        # grab the last dimension of `representation`
        representation_hidden_units = [
                layer for layer in list(self.representation.modules())\
                        if hasattr(layer, 'out_features')][-1].out_features


        if output_regression is None:
            # make the output regression as simple as a linear one
            # if nothing is specified
            self._output_regression = torch.nn.ModuleList(
                    [
                        torch.nn.Linear(representation_hidden_units, measurement_dimension)\
                                for _ in range(2) # now we hard code # of parameters
                    ])

            def output_regression(theta):
                return [f(theta) for f in self._output_regression]

        self.output_regression = output_regression
        self.measurement_dimension=measurement_dimension 
        self.noise_model = noise_model
        self.representation_hidden_units = representation_hidden_units

    def forward(self, g):
        """ Forward pass.
        """
        # graph representation $\mathcal{G}$
        # ->
        # latent representation $h$
        h = self.representation(g)

        # latent representation $h$
        # ->
        # parameters $\theta$
        theta = self.output_regression(h)
       
        return theta

    def _condition(self, g):
        """ Compute the output distribution.
        """

        if self.noise_model == 'normal-heteroschedastic':
            mu, log_sigma = self.forward(g)
            distribution = torch.distributions.normal.Normal(
                    loc=mu,
                    scale=torch.exp(log_sigma))

        elif self.noise_model == 'normal-homoschedastic':
            mu, _ = self.forward(g)

            # initialize a `LOG_SIMGA` if there isn't one
            if not hasattr(self, 'LOG_SIGMA'):
                self.LOG_SIGMA = torch.zeros((1, self.measurement_dimension))
                self.LOG_SIGMA.requires_grad = True

            distribution = torch.distributions.normal.Normal(
                    loc=mu,
                    scale=torch.exp(self.LOG_SIGMA))

        elif self.noise_model == 'normal-homoschedastic-fixed':
            mu, _ = self.forward(g)
            distribution = torch.distributions.normal.Normal(
                    loc=mu, 
                    scale=torch.ones((1, self.measurement_dimension)))

        else:
            assert isinstance(
                    self.noise_model,
                    dict)

            distribution = self.noise_model[distribution](
                    self.noise_model[kwargs])


        return distribution

    def condition(self, g, sampler=None, n_samples=64):
        """ Compute the output distribution with sampled weights.

        """
        if sampler is None:
            return self._condition(g)

        if not hasattr(sampler, 'sample_params'):
            return self._condition(g)

        # initialize a list of distributions
        distributions = []

        for _ in range(n_samples):
            sampler.sample_params()
            distributions.append(self._condition(g))

        # get the parameter of these distributions
        # NOTE: this is not necessarily the most efficienct solution
        # since we don't know the memory footprint of 
        # torch.distributions
        mus, sigmas = zip(*[
                (distribution.loc, distribution.scale)
                for distribution in distributions])

        # concat parameters together
        # (n_samples, batch_size, measurement_dimension)
        mu = torch.stack(mus).cpu() # distribution no cuda
        sigma = torch.stack(sigmas).cpu()

        # construct the distribution
        distribution = torch.distributions.normal.Normal(
                loc=mu,
                scale=sigma)

        # make it mixture
        distribution = torch.distributions.mixture_same_family\
                .MixtureSameFamily(
                        torch.distributions.Categorical(
                            torch.ones(mu.shape[0],)),
                        torch.distributions.Independent(distribution, 2))
       
        return distribution

    def loss(self, g, y):
        """ Compute the loss with a input graph and a set of parameters.
        """

        distribution = self.condition(g)

        return -distribution.log_prob(y)
