from fastapi import Depends, HTTPException, status, Form
from typing import List, Optional, Callable, Union
from helper import verify_token
from graphqlschema.schema import (
    UserInformation
)

class PermissionChecker:
    def __init__(self, required_stores: Optional[List[str]] = None, required_roles: Optional[List[str]] = None):
        self.required_stores = required_stores
        self.required_roles = required_roles

    async def __call__(self, user: UserInformation = Depends(verify_token)) -> UserInformation:
        # 1. 检查角色权限
        if self.required_roles:
            if not all(auth in self.required_roles for auth in user.authorize):
            #if user.authorize not in self.required_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have the required role permission."
                )

        # 2. 检查门店权限
        if self.required_stores:
            user_stores = set(user.store or [])
            required_stores_set = set(self.required_stores)
            if not required_stores_set.issubset(user_stores):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to access these stores."
                )

        # 3. 返回 user，后面接口还可以用
        return user

# ✅ 加一个工厂函数，支持动态store传入
def get_permission_checker(required_roles: Optional[List[str]] = None):
    def checker(
        store: Union[str, List[str]] = Form(...),  # ✅ 支持 str 或 List[str]
        user: UserInformation = Depends(verify_token)
    ) -> UserInformation:
        # 角色校验
        if required_roles and not all(auth in required_roles for auth in user.authorize):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have the required role permission."
            )
        # 统一成列表
        if isinstance(store, str):
            store_list = [store]
        else:
            store_list = store
        # store权限校验
        user_stores = set(user.store or [])
        if not set(store_list).issubset(user_stores):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to access these stores."
            )
        return user
    return checker