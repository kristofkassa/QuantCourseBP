from __future__ import annotations
from abc import ABC
from src.model import *
import numpy as np
from contract import Contract


class NumericalMethod(ABC):
    def __init__(self, model: MarketModel, params: Params) -> None:
        self._model = model
        self._params = params

    @staticmethod
    def get_numerical_methods() -> dict[str, NumericalMethod]:
        return {cls.__name__: cls for cls in NumericalMethod.__subclasses__()}


# todo: to be implemented
class MCMethod(NumericalMethod):
    def __init__(self, model: MarketModel, params: MCParams):
        if not isinstance(params, MCParams):
            raise TypeError('Params must be an instance of class MCParams')
        super().__init__(model, params)

    def find_simulation_tenors(self, contract_timeline: list[float]) -> list[float]:
        final_tenor = max(contract_timeline)
        dt = 1 / self._params.tenor_frequency
        num_of_tenors = int(final_tenor / dt)
        model_tenors = [i * dt for i in range(num_of_tenors)]
        all_simul_tenors = sorted(model_tenors + contract_timeline)
        return all_simul_tenors

    def generate_std_norm(self, num_of_tenors: int) -> np.array:
        np.random.seed(self._params.seed)
        if self._params.antithetic:
            rnd1 = np.random.standard_normal(size=(int(self._params.num_of_paths / 2), num_of_tenors))
            rnd2 = -rnd1
            rnd = np.concatenate((rnd1, rnd2), axis=0)
            if self._params.num_of_paths % 2 == 1:
                zeros = np.zeros((1, self._params.num_of_tenors))
                rnd = np.concatenate((rnd, zeros), axis=0)
        else:
            rnd = np.random.standard_normal(size=(self._params.num_of_paths, self._params.num_of_tenors))
        if self._params.standardize:
            mean = np.mean(rnd)
            std = np.std(rnd)
            rnd = (rnd - mean) / std
        return rnd

    def simulate_spot_paths(self, contract: Contract):
        model = self._model
        contract_tenors = contract.get_timeline()
        simulation_tenors = self.find_simulation_tenors(contract_tenors)
        num_of_tenors = len(simulation_tenors)
        num_of_paths = self._params.num_of_paths
        rnd_num = self.generate_std_norm(num_of_tenors)
        spot_paths = np.empty(shape=(num_of_paths, num_of_tenors))
        initial_spot = model.get_initial_spot()
        vol = model.get_vol(contract.get_strike(), contract.get_expiry())
        for path in range(num_of_paths):
            for t_idx in range(num_of_tenors):
                t_from = simulation_tenors[t_idx - 1]
                t_to = simulation_tenors[t_idx]
                spot_from = initial_spot if t_idx == 0 else spot_paths[path, t_idx - 1]
                z = rnd_num[path, t_idx]
                spot_paths[path, t_idx] = model.evolve_simulated_spot(vol, t_from, t_to, spot_from, z)
        contract_tenor_idx = [idx for idx in range(num_of_tenors) if simulation_tenors[idx] in contract_tenors]
        return spot_paths[:, contract_tenor_idx]


# todo: to be implemented
class PDEMethod(NumericalMethod):
    def __init__(self, model: MarketModel, params: PDEParams):
        if not isinstance(params, PDEParams):
            raise TypeError('Params must be an instance of class PDEParams')
        super().__init__(model, params)


class SimpleBinomialTree(NumericalMethod):
    def __init__(self, params: TreeParams, model: FlatVolModel):
        super().__init__(model, params)
        self._spot_tree_built = False
        self._df_computed = False
        self._prob_computed = False

    def init_tree(self):
        self.build_spot_tree()
        self.compute_df()
        self.compute_prob()

    def build_spot_tree(self):
        if self._spot_tree_built:
            pass
        self._down_log_step = np.log(self._params.down_step_mult)
        self._up_log_step = np.log(self._params.up_step_mult)
        tree = []
        initial_log_spot = np.log(self._model.get_initial_spot())
        previous_level = [initial_log_spot]
        tree += [previous_level]
        for _ in range(self._params.nr_steps):
            new_level = [s + self._down_log_step for s in previous_level]
            new_level += [previous_level[-1] + self._up_log_step]
            tree += [new_level]
            previous_level = new_level

        self._spot_tree = tree
        self._spot_tree_built = True

    def compute_df(self):
        if self._df_computed:
            pass
        delta_t = self._params.exp / self._params.nr_steps
        df_1_step = self._model.get_df(delta_t)
        self._df = [df_1_step ** k for k in range(self._params.nr_steps + 1)]
        self._df_computed = True

    def compute_prob(self):
        if self._prob_computed:
            pass
        if not self._df_computed:
            self._compute_df()
        p = (1 / self._df[1] - np.exp(self._down_log_step)) / (np.exp(self._up_log_step) - np.exp(self._down_log_step))
        q = 1 - p
        self._prob = (p, q)
        self._prob_computed = True


class BalancedSimpleBinomialTree(SimpleBinomialTree):
    def __init__(self, params: TreeParams, model: MarketModel):
        up = BalancedSimpleBinomialTree.calc_up_step_mult(
            model.get_rate(),
            model.get_vol(params.strike, params.exp),
            params.nr_steps,
            params.exp)
        down = BalancedSimpleBinomialTree.calc_down_step_mult(
            model.get_rate(),
            model.get_vol(params.strike, params.exp),
            params.nr_steps,
            params.exp)
        p = TreeParams(params.exp, params.strike, params.nr_steps, up, down)
        super().__init__(p, model)

    @staticmethod
    def calc_up_step_mult(rate: float, vol: float, nr_steps: int, exp: float) -> float:
        delta_t = exp / nr_steps
        log_mean = rate * delta_t - 0.5 * vol ** 2 * delta_t
        return np.exp(log_mean + vol * np.sqrt(delta_t))

    @staticmethod
    def calc_down_step_mult(rate: float, vol: float, nr_steps: int, exp: float) -> float:
        delta_t = exp / nr_steps
        log_mean = rate * delta_t - 0.5 * vol ** 2 * delta_t
        return np.exp(log_mean - vol * np.sqrt(delta_t))


class AnalyticMethod(NumericalMethod):
    def __init__(self, model: MarketModel):
        super().__init__(model, Params())


class Params(ABC):
    def to_dict(self) -> dict[str, object]:
        return vars(self)


class MCParams(Params):
    def __init__(self) -> None:
        # todo: to be implemented, a few examples:
        self.seed: int = 0
        self.num_of_paths: int = 100
        self.timestep: int = 10


class PDEParams(Params):
    def __init__(self) -> None:
        # todo: to be implemented
        pass


class TreeParams(Params):
    def __init__(self, exp: float, strike: float, nr_steps: int = 1, up_step_mult: float = np.nan,
                 down_step_mult: float = np.nan) -> None:
        self.exp = exp
        self.nr_steps = nr_steps
        self.up_step_mult = up_step_mult
        self.down_step_mult = down_step_mult
        self.strike = strike