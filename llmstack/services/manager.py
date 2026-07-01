import abc


class ServiceManager(abc.ABC):
    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def ensure_running(self):
        raise NotImplementedError

    @abc.abstractmethod
    def restart(self):
        raise NotImplementedError

    @abc.abstractmethod
    def stop(self):
        raise NotImplementedError

    @abc.abstractmethod
    def is_healthy(self) -> bool:
        raise NotImplementedError

    def health(self) -> bool:
        return self.is_healthy()
