from fastapi import APIRouter

router = APIRouter(tags=["tables"])
# 后续按资源 include 子 router

__all__ = ["router"]
