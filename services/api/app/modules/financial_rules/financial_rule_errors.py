class FinancialRuleNotFoundError(Exception):
    """
    Raised when a financial rule does not exist or does not belong to the user.

    What:
        Represents a missing (or foreign) rule in the financial_rules module.

    Why:
        A foreign and a nonexistent rule are indistinguishable to the caller
        (404), so rule ids of other users are never confirmed.
    """

    pass


class FinancialRuleAlreadyExistsError(Exception):
    """
    Raised when a second floor, overcommitment alert or budget alert would be
    created for the same subject.

    What:
        Represents the partial uniqueness of the rule types that are limited
        to one rule per user and subject (409).

    Why:
        The partial UNIQUE indexes are the database backstop; the service
        checks first under the user lock and also translates a violation that
        still slips through, so the caller never sees a raw IntegrityError.
    """

    pass


class FinancialRuleInvalidTransitionError(Exception):
    """
    Raised when a requested status transition is not allowed from the rule's
    current status (409).
    """

    pass


class FinancialRuleActivationNotAvailableError(Exception):
    """
    Raised when enabling a rule whose runtime does not exist yet (409).

    What:
        Income-allocation rules stay drafts in VF-020E5 (no AUTO / CONFIRM
        execution exists), and alert rules stay drafts until the alert
        runtime exists.

    Why:
        A rule must never look operational when nothing evaluates it.
    """

    pass


class FinancialRuleDeletionNotAllowedError(Exception):
    """
    Raised when a rule is deleted outside the statuses that allow deletion
    (draft or disabled) (409).
    """

    pass


class FinancialRuleSubjectArchivedError(Exception):
    """
    Raised when an allocation rule would be created or edited against an
    archived source Account or an archived target Goal (409).
    """

    pass


class FinancialRuleCurrencyMismatchError(Exception):
    """
    Raised when an allocation rule's source Account and a target Goal do not
    share one currency (422).
    """

    pass


class FinancialRuleInvalidFieldsError(Exception):
    """
    Raised when a request carries fields that are not valid for the rule's
    type or are semantically inconsistent (422).

    What:
        Carries a short, constraint-free message that is safe to return.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
