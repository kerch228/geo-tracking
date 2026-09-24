from typing import Annotated

from fastapi import Header, HTTPException, status


async def get_current_user_id(
    x_user_id: Annotated[
        str,
        Header(alias="X-User-Id", min_length=1, max_length=128),
    ],
) -> str:
    user_id = x_user_id.strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="X-User-Id must not be empty",
        )
    return user_id
