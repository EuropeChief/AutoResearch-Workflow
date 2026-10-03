"""Trusted, synthetic CUDA workload. No task candidate or learning is involved."""


def evaluate(torch):
    matrix = torch.randint(0, 16, (128, 128), device='cuda:0').float()
    return matrix, matrix @ torch.eye(128, device='cuda:0')
