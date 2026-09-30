from fastapi import APIRouter, Depends, HTTPException

from crm.core.state import get_current_user
from crm.services.dashboard_scope import resolve_lead_view_or_403
from crm.services.lead_location_fields import coalesce_locations


router = APIRouter()


@router.get("/leads/{lead_id}/suggestions")
async def get_cross_pitch_suggestions(lead_id: str, current_user: dict = Depends(get_current_user)):
    lead = await resolve_lead_view_or_403(lead_id, current_user)

    suggestions = []
    current_project = str(lead.get("project") or "").strip()

    projects = {
        "Reserve 16": {"min_budget": "1cr", "type": "Villa Plots", "location": "ECR Pattipulam"},
        "Krsna": {"min_budget": "3cr", "type": "3 BHK Homes", "location": "Abhiramapuram"},
        "Vivriti": {"min_budget": "4cr", "type": "4 BHK Apartments", "location": "OMR Kottivakkam"},
        "Mélange": {"min_budget": "2cr", "type": "3 & 4 BHK Homes", "location": "Saligramam"},
    }

    # #51: location is a list (or a legacy scalar string) — matching any of
    # the lead's locations is enough.
    loc = " ".join(coalesce_locations(lead)).lower()

    for project, details in projects.items():
        if project.lower() != current_project.lower():
            suggestions.append(
                {
                    "project": project,
                    "reason": f"Consider {project} - {details['type']} in {details['location']}",
                    "match_score": 0.8 if details["location"].lower() in loc else 0.5,
                }
            )

    return suggestions

