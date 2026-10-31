import copy
import gc

import torch
import torch.multiprocessing as mp


class FakeQueue:
    def put(self, arg):
        del arg

    def get_nowait(self):
        raise mp.queues.Empty

    def qsize(self):
        return 0

    def empty(self):
        return True


def clone_obj(obj):
    clone_obj = copy.deepcopy(obj)
    for attr in clone_obj.__dict__.keys():
        # check if its a property
        if hasattr(clone_obj.__class__, attr) and isinstance(
            getattr(clone_obj.__class__, attr), property
        ):
            continue
        if isinstance(getattr(clone_obj, attr), torch.Tensor):
            setattr(clone_obj, attr, getattr(clone_obj, attr).detach().clone())
    return clone_obj


def clone_tensor_tree(obj):
    """Clone every tensor in a nested transport payload into this process.

    CUDA tensors received through ``torch.multiprocessing.Queue`` retain CUDA IPC
    storage owned by the producer.  A long-lived consumer must not keep those
    tensors after the producer exits, so queue payloads are adopted by cloning
    their tensor leaves before the transport object is released.
    """

    if isinstance(obj, torch.Tensor):
        return obj.detach().clone()
    if isinstance(obj, dict):
        return {key: clone_tensor_tree(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [clone_tensor_tree(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(clone_tensor_tree(value) for value in obj)
    return copy.deepcopy(obj)


def release_cuda_ipc_cache():
    """Release dead CUDA IPC mappings before either process terminates."""

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.ipc_collect()
