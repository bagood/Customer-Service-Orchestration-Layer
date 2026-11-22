def export_context(workflow):
    context = workflow.context()
    offer, shortfall = context["offer"], context["shortfall"]
    exported = {}
    if offer:
        exported["offer"] = offer
    if shortfall is not None:
        exported["shortfall"] = shortfall
    return exported


def clear_offer(workflow):
    workflow.context().reset("offer", "offer_presented_turn", "shortfall")
