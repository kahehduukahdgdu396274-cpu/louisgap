from datetime import datetime
class ShadowGovernanceReportGenerator:
    """
    P20-12.5
    Generate governance report from shadow snapshot.
    Read-only observation output.
    """
    def generate(self, snapshot):
        writers = snapshot.get("writers", {})
        violations = []
        for writer, info in writers.items():
            if writer.startswith("unknown"):
                violations.append({
                    "writer": writer,
                    "status": "UNKNOWN",
                    "permission": "BLOCK",
                })
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "mode": "shadow",
            "observe_only": True,
            "total_events": snapshot.get(
                "total_events",
                0
            ),
            "writers": writers,
            "violations": violations,
            "status": (
                "REVIEW_REQUIRED"
                if violations
                else "PASS"
            ),
        }
