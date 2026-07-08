# Fetch Engine Research

NOAFF 的采集链路现在采用 `multi_engine` 默认策略，而不是单押 Scrapling 或 Firecrawl。

## 已整合

| 项目 | 参考点 | 当前落地 |
| --- | --- | --- |
| `lexiforest/curl_cffi` | 浏览器 TLS / JA3 / HTTP2 指纹伪装，requests-like API，低成本 | 新增 `CurlCffiFetcher`，作为 `multi_engine` 第一层 |
| Scrapling | Fetcher / DynamicFetcher / StealthyFetcher，自适应选择器，本地浏览器增强 | 作为 `multi_engine` 的标准、增强、高兼容升级层 |

## 继续保留为可选方案

| 项目 | 可参考点 | 暂不默认集成原因 |
| --- | --- | --- |
| `Flaresolverr/Flaresolverr` | 独立服务、浏览器会话、返回 cookies / HTML | 需要常驻服务和更多内存，适合作为后续“本地外部解题服务”选项 |
| `ultrafunkamsterdam/nodriver` | CDP 直连浏览器、无 Selenium webdriver 痕迹、`cf_verify` 思路 | 值得作为后续高兼容浏览器后端，但需要异步浏览器生命周期和资源治理 |
| `hawkli-1994/CF-Ares` | 浏览器拿会话后交给 `curl_cffi` 复用的两段式架构 | 架构思路已采纳：轻量请求优先，浏览器层作为升级；完整方案会引入更多代理/验证码边界 |
| `dairoot/CloudFlare5sBypass` | 本地服务返回 clearance cookies | 依赖 OCR / 图像识别 / 服务化部署，维护成本较高 |
| `VeNoMouS/cloudscraper` | requests-compatible Cloudflare IUAM 解题器 | 对现代 Turnstile/CAPTCHA 可靠性有限，且包含第三方 CAPTCHA solver 接口，不作为默认路径 |

## 当前默认链路

```text
multi_engine
  -> curl_cffi
  -> scrapling_standard
  -> scrapling_dynamic
  -> scrapling_stealth
```

目标是先用最低成本拿到真实 HTML；只有低成本失败时才启动本地浏览器增强层，避免定时监控把资源或外部 credits 烧光。

