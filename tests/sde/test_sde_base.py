import jax
import jax.numpy as jnp
from jax import random
import pytest
import equinox as eqx

from linsdex.sde.sde_base import (
  AbstractSDE,
  AbstractLinearSDE,
  AbstractLinearTimeInvariantSDE,
  TimeScaledLinearTimeInvariantSDE
)
from linsdex.sde.sde_examples import BrownianMotion, OrnsteinUhlenbeck
from linsdex.matrix.diagonal import DiagonalMatrix
from linsdex.matrix.dense import DenseMatrix
from linsdex.matrix.matrix_base import TAGS
from linsdex.potential.gaussian.transition import GaussianTransition
from linsdex.potential.gaussian.dist import MixedGaussian
from linsdex.potential.gaussian.gaussian_potential_series import GaussianPotentialSeries
import linsdex.util as util


class TestAbstractSDE:
  """Test the abstract SDE base class interface"""

  def test_abstract_sde_cannot_be_instantiated(self):
    """Abstract SDE should not be instantiable"""
    with pytest.raises(TypeError):
      AbstractSDE()


class TestAbstractLinearSDE:
  """Test abstract linear SDE functionality"""

  def test_abstract_linear_sde_cannot_be_instantiated(self):
    """Abstract linear SDE should not be instantiable"""
    with pytest.raises(TypeError):
      AbstractLinearSDE()


class TestAbstractLinearTimeInvariantSDE:
  """Test abstract linear time-invariant SDE functionality"""

  def test_abstract_lti_sde_cannot_be_instantiated(self):
    """Abstract LTI SDE should not be instantiable"""
    with pytest.raises(TypeError):
      AbstractLinearTimeInvariantSDE()


class TestTimeScaledLinearTimeInvariantSDE:
  """Test time-scaled linear time-invariant SDE"""

  def test_time_scaling_initialization(self):
    """Test proper initialization of time-scaled SDE"""
    base_sde = BrownianMotion(sigma=1.0, dim=2)
    time_scale = 2.0
    scaled_sde = TimeScaledLinearTimeInvariantSDE(base_sde, time_scale)

    assert scaled_sde.sde is base_sde
    assert scaled_sde.time_scale == time_scale

  def test_time_scaling_parameters(self):
    """Test that time scaling affects F and L matrices correctly"""
    base_sde = OrnsteinUhlenbeck(sigma=1.0, lambda_=0.5, dim=2)
    time_scale = 2.0
    scaled_sde = TimeScaledLinearTimeInvariantSDE(base_sde, time_scale)

    # F should be scaled by time_scale
    expected_F_elements = base_sde.F.elements * time_scale
    assert jnp.allclose(scaled_sde.F.elements, expected_F_elements)

    # L should be scaled by sqrt(time_scale)
    expected_L_elements = base_sde.L.elements * jnp.sqrt(time_scale)
    assert jnp.allclose(scaled_sde.L.elements, expected_L_elements)

  def test_time_scaling_transitions(self):
    """Test that time scaling affects transition distributions correctly"""
    base_sde = BrownianMotion(sigma=1.0, dim=2)
    time_scale = 2.0
    scaled_sde = TimeScaledLinearTimeInvariantSDE(base_sde, time_scale)

    s, t = 0.0, 1.0
    base_transition = base_sde.get_transition_distribution(s * time_scale, t * time_scale)
    scaled_transition = scaled_sde.get_transition_distribution(s, t)

    # The transitions should be the same
    assert jnp.allclose(base_transition.A.elements, scaled_transition.A.elements)
    assert jnp.allclose(base_transition.u, scaled_transition.u)
    assert jnp.allclose(base_transition.Sigma.elements, scaled_transition.Sigma.elements)

  def test_order_attribute_passthrough(self):
    """Test that order attribute is passed through from base SDE"""
    from linsdex.sde.sde_examples import WienerVelocityModel

    base_sde = WienerVelocityModel(sigma=1.0, position_dim=2, order=2)
    time_scale = 2.0
    scaled_sde = TimeScaledLinearTimeInvariantSDE(base_sde, time_scale)

    assert scaled_sde.order == base_sde.order

  def test_order_attribute_error(self):
    """Test that accessing order on SDE without order raises AttributeError"""
    base_sde = BrownianMotion(sigma=1.0, dim=2)
    time_scale = 2.0
    scaled_sde = TimeScaledLinearTimeInvariantSDE(base_sde, time_scale)

    with pytest.raises(AttributeError, match="does not have an order"):
      _ = scaled_sde.order


class TestLinearSDETransitions:
  """Test transition distribution computations for linear SDEs"""

  def test_brownian_motion_transitions(self):
    """Test transition distributions for Brownian motion"""
    sigma = 1.0
    dim = 2
    sde = BrownianMotion(sigma=sigma, dim=dim)

    s, t = 0.0, 1.0
    dt = t - s

    transition = sde.get_transition_distribution(s, t)

    # For Brownian motion: A = I, u = 0, Sigma = sigma^2 * dt * I
    expected_A = jnp.eye(dim)
    expected_u = jnp.zeros(dim)
    expected_Sigma = sigma**2 * dt * jnp.eye(dim)

    assert jnp.allclose(transition.A.as_matrix(), expected_A)
    assert jnp.allclose(transition.u, expected_u)
    assert jnp.allclose(transition.Sigma.as_matrix(), expected_Sigma)


class TestLinearSDEConditioning:
  """Test conditioning of linear SDEs on evidence"""

  def test_condition_on_evidence(self):
    """Test conditioning a linear SDE on evidence"""
    sde = BrownianMotion(sigma=1.0, dim=2)

    # Create evidence
    x0 = jnp.ones(2) * 5.0
    Sigma0 = DiagonalMatrix.eye(2) * 0.001
    potential = MixedGaussian(x0, Sigma0.get_inverse())
    ts = jnp.array([1.1])
    node_potentials = potential[None]

    evidence = GaussianPotentialSeries(ts, node_potentials)
    conditioned_sde = sde.condition_on(evidence)

    from linsdex.sde.conditioned_linear_sde import ConditionedLinearSDE
    assert isinstance(conditioned_sde, ConditionedLinearSDE)
    assert conditioned_sde.sde is sde
    assert conditioned_sde.evidence is evidence


class TestLinearSDEBatchHandling:
  """Test batch handling in linear SDEs"""

  def test_batch_size_property(self):
    """Test batch size property for different matrix types"""
    # Non-batched SDE
    sde = BrownianMotion(sigma=1.0, dim=2)
    assert sde.batch_size is None

    # Test with batched diagonal matrix
    batch_size = 3
    F_elements = jnp.zeros((batch_size, 2))
    L_elements = jnp.ones((batch_size, 2))

    F = DiagonalMatrix(F_elements, tags=TAGS.no_tags)
    L = DiagonalMatrix(L_elements, tags=TAGS.no_tags)

    from linsdex.sde.sde_examples import LinearTimeInvariantSDE
    batched_sde = LinearTimeInvariantSDE(F=F, L=L)
    assert batched_sde.batch_size == batch_size


if __name__ == "__main__":
  pytest.main([__file__])