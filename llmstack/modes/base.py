from abc import ABC, abstractmethod


class LoopMode(ABC):
    @abstractmethod
    def next_task(self):
        raise NotImplementedError

    @abstractmethod
    def on_result(self, task, outcome, state):
        raise NotImplementedError

    @abstractmethod
    def on_incomplete(self, task, executor_type):
        raise NotImplementedError
