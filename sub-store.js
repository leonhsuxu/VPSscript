// sub-store.js 配置文件 (基于 v6 版本逻辑)

// ========================== 可配置区域 ==========================
// 在这里填入您的所有订阅链接
const subscriptions = [
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4"
];

// 节点重命名的前缀
const providerPrefixes = ['丑团1', '丑团2', '丑团3', '丑团4'];

// 健康检查URL和间隔
const testUrl = "http://www.gstatic.com/generate_204";
const testInterval = 300;
// ======================= End of 可配置区域 =======================


// 定义地区分组的正则表达式和图标 (使用 v6 的无前缀命名)
const buckets = {
    '🇭🇰 香港': { regex: /港|HK|Hong Kong/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Hong_Kong.png' },
    '🇯🇵 日本': { regex: /日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Japan.png' },
    '🇸🇬 狮城': { regex: /新加坡|🇸🇬|sg|singapore|坡|狮城/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Singapore.png' },
    '🇺🇸 美国': { regex: /^(?!.*(?:aus|rus)).*(?:\b(?:us|usa|american|united states)\b|美|🇺🇸|波特兰|达拉斯|俄regon|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥)/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/United_States.png' },
    '🇹🇼 湾省': { regex: /台湾|🇹🇼|tw|taiwan|台|新北|彰化/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Taiwan.png' },
    '🇰🇷 韩国': { regex: /韩|🇰🇷|kr|korea|kor|首尔|韓/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Korea.png' },
    '🇩🇪 德国': { regex: /德国|🇩🇪|\bde\b|germany/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Germany.png' }
};

// 主处理函数
module.exports.parse = async (raw, { axios, yaml, console }) => {
    const proxies = yaml.parse(raw).proxies;

    // 1. 为来自不同订阅的节点添加前缀
    const allProxies = subscriptions.flatMap((sub, index) => {
        const prefix = providerPrefixes[index] || `Sub${index + 1}`;
        return proxies.filter(p => p.sub === sub).map(p => {
            p.name = `[${prefix}] ${p.name}`;
            return p;
        });
    });

    // 2. 自动进行地区分组
    const groupedProxies = {};
    const matchedProxies = new Set();

    for (const [groupName, { regex }] of Object.entries(buckets)) {
        groupedProxies[groupName] = [];
        for (const proxy of allProxies) {
            if (regex.test(proxy.name) && !matchedProxies.has(proxy.name)) {
                groupedProxies[groupName].push(proxy.name);
                matchedProxies.add(proxy.name);
            }
        }
    }
    
    // 创建“其他”分组
    const otherProxies = allProxies.filter(p => !matchedProxies.has(p.name)).map(p => p.name);
    groupedProxies['🇺🇳 其他'] = otherProxies;

    // 【动态特性】过滤掉没有节点的空分组
    const nonEmptyGroups = Object.entries(groupedProxies).filter(([, proxies]) => proxies.length > 0);

    // 3. 构建完整的 Clash 配置
    const config = {
        'mixed-port': 7890,
        'allow-lan': true,
        'mode': 'rule',
        'log-level': 'info',
        'external-controller': '127.0.0.1:9090',
        'proxies': allProxies,
        'proxy-groups': [
            // --- 核心入口 ---
            { name: '🚀 节点选择', type: 'select', proxies: ['♻️ 自动选择', '🔯 故障转移', ...nonEmptyGroups.map(([name]) => name), 'DIRECT'], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Airport.png'},
            // --- 功能分组 ---
            { name: '♻️ 自动选择', type: 'url-test', proxies: allProxies.map(p => p.name), url: testUrl, interval: testInterval, tolerance: 50, lazy: true, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Auto.png' },
            { name: '🔯 故障转移', type: 'fallback', proxies: allProxies.map(p => p.name), url: testUrl, interval: testInterval, lazy: true, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Loop.png' },
            { name: '🌏 直连优选', type: 'fallback', proxies: ['DIRECT', '🚀 节点选择'], url: testUrl, interval: testInterval, lazy: true, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Global.png'},
            // --- 应用分组 ---
            { name: '🎬 Emby', type: 'select', proxies: ['DIRECT', '🚀 节点选择', ...nonEmptyGroups.map(([name]) => name)], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Emby.png' },
            { name: '💬 Telegram', type: 'select', proxies: ['🚀 节点选择', ...nonEmptyGroups.map(([name]) => name)], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Telegram.png' },
            { name: '📺 YouTube', type: 'select', proxies: ['🚀 节点选择', ...nonEmptyGroups.map(([name]) => name)], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/YouTube.png' },
            // --- 地区分组 (自动生成) ---
            ...nonEmptyGroups.map(([name, proxies]) => ({
                name,
                type: 'fallback',
                proxies,
                url: testUrl,
                interval: testInterval,
                lazy: true,
                icon: (buckets[name] || {}).icon || 'https://fastly.jsdelivr.net/gh/Koolson/Qure/IconSet/Color/World_Map.png'
            }))
        ],
        'rules': [
            "DOMAIN-SUFFIX,lite.cn2gias.uk,🎬 Emby",
            "DOMAIN-SUFFIX,feiniu.lol,🎬 Emby",
            "DOMAIN-SUFFIX,ciallo.party,🎬 Emby",
            "DOMAIN-SUFFIX,liminalnet.com,🎬 Emby",
            "DOMAIN-SUFFIX,5670320.xyz,🎬 Emby",
            "PROCESS-NAME,com.mountains.hills,DIRECT",
            "DOMAIN-SUFFIX,10520.xyz,DIRECT", "DOMAIN-SUFFIX,jsq.vban.xyz,DIRECT", "DOMAIN-SUFFIX,coemn.com,DIRECT", "DOMAIN-SUFFIX,embycc.link,DIRECT", "DOMAIN-SUFFIX,shrekmedia.org,DIRECT", "DOMAIN-SUFFIX,wenjian.de,DIRECT", "DOMAIN-SUFFIX,hohai.eu.org,DIRECT", "DOMAIN-SUFFIX,cerda.eu.org,DIRECT", "DOMAIN-SUFFIX,seraphine.eu.org,DIRECT", "DOMAIN-SUFFIX,kowo.eu.org,DIRECT", "DOMAIN-SUFFIX,libilibi.eu.org,DIRECT", "DOMAIN-SUFFIX,nouon.eu.org,DIRECT", "DOMAIN-SUFFIX,feiyue.lol,DIRECT", "DOMAIN-SUFFIX,aliz.work,DIRECT", "DOMAIN-SUFFIX,emos.lol,DIRECT", "DOMAIN-SUFFIX,emos.movier.ink,DIRECT", "DOMAIN-SUFFIX,emos.dolby.dpdns.org,DIRECT", "DOMAIN-SUFFIX,bangumi.ca,DIRECT", "DOMAIN-SUFFIX,6666456.xyz,DIRECT", "DOMAIN-SUFFIX,191920.xyz,DIRECT", "DOMAIN-SUFFIX,nijigem.by,DIRECT",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/BanAD.list,REJECT",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/BanProgramAD.list,REJECT",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Telegram.list,💬 Telegram",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/YouTube.list,📺 YouTube",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/ProxyGFWlist.list,🚀 节点选择",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/UnBan.list,DIRECT",
            "GEOIP,LAN,DIRECT",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/ChinaDomain.list,DIRECT",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/ChinaCompanyIp.list,DIRECT",
            "RULE-SET,https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Download.list,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🌏 直连优选"
        ]
    };
    
    return yaml.stringify(config);
};
