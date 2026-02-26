class BackendPatchService:

    @staticmethod
    def simulate_backend_patch(patch: dict):
        """
        Example patch structure:

        {
          "add_required_fields": ["id", "name"],
          "remove_optional_fields": []
        }
        """

        added = patch.get("add_required_fields", [])
        removed = patch.get("remove_optional_fields", [])

        return {
            "message": "Backend patch simulated successfully",
            "summary": {
                "fields_to_mark_required": added,
                "fields_to_mark_optional": removed
            },
            "note": "No actual backend code was modified (safe mode)."
        }