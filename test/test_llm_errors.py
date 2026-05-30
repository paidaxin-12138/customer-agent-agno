import errno

from utils.llm_errors import is_transient_llm_transport_error


def test_broken_pipe_is_transient():
    assert is_transient_llm_transport_error(BrokenPipeError())


def test_errno_epipe_is_transient():
    assert is_transient_llm_transport_error(OSError(errno.EPIPE, "broken pipe"))


def test_value_error_not_transient():
    assert not is_transient_llm_transport_error(ValueError("bad"))
