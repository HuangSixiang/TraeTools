using Avalonia.Media;

namespace TraeTools.Models;

/// <summary>
/// 模型价目表与成本估算（本地口径，仅参考）。
/// 命中价 = 前缀缓存命中 token 的单价（约为全价的 10%）；未知名模型用默认价兜底。
/// 服务端若有真实费用字段（CostMoneyFloat &gt; 0）则优先展示官方值，估算值仅作补充。
/// </summary>
public static class ModelPricing
{
    /// <summary>(输入单价/1M, 命中输入单价/1M, 输出单价/1M)，单位：人民币元。</summary>
    private static readonly Dictionary<string, (double InM, double HitM, double OutM)> Table =
        new(StringComparer.OrdinalIgnoreCase)
        {
            // 常见模型近似价（仅供估算，后续可在设置页维护）
            ["deepseek"] = (1.0, 0.1, 2.0),
            ["doubao"] = (1.0, 0.1, 2.0),
            ["qwen"] = (2.0, 0.25, 8.0),
            ["glm"] = (4.0, 0.4, 12.0),
            ["ernie"] = (4.0, 0.4, 12.0),
            ["gpt"] = (7.5, 0.9, 30.0),
            ["kimi"] = (14.0, 2.8, 56.0),
            ["claude"] = (24.0, 4.8, 75.0),
        };

    private static readonly (double InM, double HitM, double OutM) Default = (5.0, 0.5, 15.0);

    private static (double InM, double HitM, double OutM) PriceFor(string model)
    {
        if (string.IsNullOrWhiteSpace(model)) return Default;
        foreach (var (key, val) in Table)
            if (model.IndexOf(key, StringComparison.OrdinalIgnoreCase) >= 0) return val;
        return Default;
    }

    /// <summary>估算一次会话成本（元）：未命中输入走全价，命中输入走命中价，输出走输出价。</summary>
    public static double EstimateCost(long input, long output, long cacheRead, string model)
    {
        if (input < 0) input = 0;
        if (output < 0) output = 0;
        if (cacheRead < 0) cacheRead = 0;
        var (inM, hitM, outM) = PriceFor(model);
        long fresh = input - Math.Min(cacheRead, input);
        return fresh / 1e6 * inM + cacheRead / 1e6 * hitM + output / 1e6 * outM;
    }

    /// <summary>金额显示：≥1000 加千分位，否则两位小数。</summary>
    public static string Format(double v) => v >= 1000 ? $"¥{v:0,0.0}" : $"¥{v:0.00}";

    /// <summary>缓存健康三色（>=20% 正常 / 5~20% 偏低 / 其余 疑似无缓存）。</summary>
    public static (double Rate, string Text, string Kind, IBrush Bg, IBrush Fg) Health(double hitRate)
    {
        if (hitRate >= 20)
            return (20, "缓存正常", "ok",
                new SolidColorBrush(Color.FromArgb(0x1A, 0x10, 0xB9, 0x81)),
                new SolidColorBrush(Color.FromRgb(0x10, 0xB9, 0x81)));
        if (hitRate >= 5)
            return (5, "缓存偏低", "warn",
                new SolidColorBrush(Color.FromArgb(0x1A, 0xF5, 0x9E, 0x0B)),
                new SolidColorBrush(Color.FromRgb(0xD9, 0x77, 0x06)));
        return (0, "疑似无缓存", "bad",
            new SolidColorBrush(Color.FromArgb(0x1A, 0xEF, 0x44, 0x44)),
            new SolidColorBrush(Color.FromRgb(0xDC, 0x26, 0x26)));
    }
}