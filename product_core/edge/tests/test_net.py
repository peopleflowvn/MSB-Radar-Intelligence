# -*- coding: utf-8 -*-
"""Chính sách proxy + chứng chỉ TLS dùng chung (app/net.py) cho mạng công ty."""
import os
import unittest
from unittest import mock

from app import net


class _Cfg:
    def __init__(self, proxy_url="", ssl_verify=True, ssl_ca_bundle=""):
        self.proxy_url = proxy_url
        self.ssl_verify = ssl_verify
        self.ssl_ca_bundle = ssl_ca_bundle


class ResolveProxiesTest(unittest.TestCase):
    def test_de_trong_thi_lay_proxy_he_thong(self):
        with mock.patch.object(net, "system_proxies",
                               return_value={"https": "http://sys:8080"}):
            self.assertEqual(net.resolve_proxies(_Cfg()),
                             {"https": "http://sys:8080"})

    def test_de_trong_va_khong_co_proxy_he_thong_thi_None(self):
        with mock.patch.object(net, "system_proxies", return_value={}):
            self.assertIsNone(net.resolve_proxies(_Cfg()))

    def test_off_thi_ep_di_thang(self):
        self.assertIs(net.resolve_proxies(_Cfg(proxy_url="off")), net._DIRECT)

    def test_dia_chi_tuong_minh_them_scheme(self):
        self.assertEqual(net.resolve_proxies(_Cfg(proxy_url="proxy.corp:3128")),
                         {"http": "http://proxy.corp:3128",
                          "https": "http://proxy.corp:3128"})


class VerifyForTest(unittest.TestCase):
    def test_ca_bundle_ton_tai_thi_dung_no(self):
        with mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(net.verify_for(_Cfg(ssl_ca_bundle="C:/corp/ca.pem")),
                             "C:/corp/ca.pem")

    def test_tat_kiem_tra_thi_False(self):
        with mock.patch.object(net, "windows_ca_bundle", return_value=None):
            self.assertFalse(net.verify_for(_Cfg(ssl_verify=False)))

    def test_mac_dinh_dung_bundle_windows_neu_co(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(net, "windows_ca_bundle", return_value="C:/x/ca_win.pem"):
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
            self.assertEqual(net.verify_for(_Cfg()), "C:/x/ca_win.pem")

    def test_mac_dinh_True_khi_khong_co_gi(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(net, "windows_ca_bundle", return_value=None):
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
            self.assertIs(net.verify_for(_Cfg()), True)


class ApplyTest(unittest.TestCase):
    def test_gan_proxy_va_verify_vao_session(self):
        session = mock.Mock(trust_env=True, proxies={}, verify=True)
        with mock.patch.object(net, "resolve_proxies",
                               return_value={"https": "http://p:8080"}), \
                mock.patch.object(net, "verify_for", return_value=False):
            net.apply(session, _Cfg())
        self.assertEqual(session.proxies, {"https": "http://p:8080"})
        self.assertFalse(session.verify)

    def test_direct_tat_trust_env(self):
        session = mock.Mock(trust_env=True, proxies={"x": "y"}, verify=True)
        with mock.patch.object(net, "resolve_proxies", return_value=net._DIRECT), \
                mock.patch.object(net, "verify_for", return_value=True):
            net.apply(session, _Cfg(proxy_url="off"))
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies, {})


class ChromeArgTest(unittest.TestCase):
    def test_khong_co_dia_chi_thi_khong_them_co(self):
        self.assertEqual(net.chrome_proxy_arg(_Cfg()), "")
        self.assertEqual(net.chrome_proxy_arg(_Cfg(proxy_url="off")), "")

    def test_co_dia_chi_thi_tra_co_proxy_server(self):
        self.assertEqual(net.chrome_proxy_arg(_Cfg(proxy_url="10.0.0.1:8080")),
                         "--proxy-server=http://10.0.0.1:8080")


if __name__ == "__main__":
    unittest.main()
