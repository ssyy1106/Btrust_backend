from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models.label_template import LabelTemplate

async def get_template_by_id(db: AsyncSession, template_id: int):
    stmt = select(LabelTemplate).where(LabelTemplate.id == template_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    return record.template_json if record else None