from unittest.mock import MagicMock, patch


def test_reload_satosa_success():
    mock_container = MagicMock()
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    with patch("app.satosa_reload.docker.from_env", return_value=mock_client):
        from app.satosa_reload import reload_satosa
        result = reload_satosa()

    assert result is True
    mock_container.restart.assert_called_once_with(timeout=10)


def test_reload_satosa_container_not_found():
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = Exception("container not found")

    with patch("app.satosa_reload.docker.from_env", return_value=mock_client):
        from app.satosa_reload import reload_satosa
        result = reload_satosa()

    assert result is False


def test_reload_satosa_docker_unavailable():
    with patch("app.satosa_reload.docker.from_env", side_effect=Exception("socket not found")):
        from app.satosa_reload import reload_satosa
        result = reload_satosa()

    assert result is False
