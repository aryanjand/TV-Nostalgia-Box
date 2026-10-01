def test_tv90_package_imports() -> None:
    import tv90

    assert tv90.__name__ == "tv90"


def test_domain_package_imports() -> None:
    import tv90.domain

    assert tv90.domain.__name__ == "tv90.domain"


def test_ports_package_imports() -> None:
    import tv90.ports

    assert tv90.ports.__name__ == "tv90.ports"


def test_adapters_package_imports() -> None:
    import tv90.adapters

    assert tv90.adapters.__name__ == "tv90.adapters"


def test_application_package_imports() -> None:
    import tv90.application

    assert tv90.application.__name__ == "tv90.application"


def test_interface_package_imports() -> None:
    import tv90.interface

    assert tv90.interface.__name__ == "tv90.interface"
