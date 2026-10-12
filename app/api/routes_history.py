"""
API Routes - Junction Audit History
"""
from fastapi import APIRouter, Depends, Request, Query
from typing import List
from app.api.schemas import AuditLogEntry
from app.application.traffic_service import TrafficService

router = APIRouter(prefix="/api/junctions", tags=["History"])


def get_traffic_service(request: Request) -> TrafficService:
    return request.app.state.traffic_service


@router.get("/{junction_id}/history", response_model=List[AuditLogEntry], summary="Get junction audit history")
async def get_junction_history(
    junction_id: str,
    limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
    service: TrafficService = Depends(get_traffic_service),
):
    jid = junction_id.upper()
    return service.get_junction_history(jid, limit=limit)
