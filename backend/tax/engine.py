from decimal import Decimal


def calculate_gift_tax(gift_amount_krw: Decimal) -> Decimal:
    """증여세 계산.

    현재는 증여금액만 계산하므로 0을 반환한다.

    추후 확장 예정:
    - 공제금액 차감 (배우자 6억, 직계존비속 5천만원 등)
    - 과세표준 계산
    - 누진세율 적용 (10% ~ 50%)
    - 10년 내 증여 합산

    Args:
        gift_amount_krw: 증여금액 (원화)

    Returns:
        예상 증여세 (원화). 현재는 항상 0.
    """
    return Decimal(0)
