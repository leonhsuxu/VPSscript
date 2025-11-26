// sub-store.js 配置文件 (基于 v6 逻辑，已修复 RULE-SET 错误)

// ========================== 可配置区域 ==========================
const subscriptions = [
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1",
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2",
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3",
  "https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4"
];

const providerPrefixes = ['丑团1', '丑团2', '丑团3', '丑团4'];
const testUrl = "http://www.gstatic.com/generate_204";
const testInterval = 300;
// ======================= End of 可配置区域 =======================

const buckets = {
    '🇭🇰 香港': { regex: /港|HK|Hong Kong/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Hong_Kong.png' },
    '🇯🇵 日本': { regex: /日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Japan.png' },
    '🇸🇬 狮城': { regex: /新加坡|🇸🇬|sg|singapore|坡|狮城/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Singapore.png' },
    '🇺🇸 美国': { regex: /^(?!.*(?:aus|rus)).*(?:\b(?:us|usa|american|united states)\b|美|🇺🇸|波特兰|达拉斯|俄regon|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥)/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/United_States.png' },
    '🇹🇼 湾省': { regex: /台湾|🇹🇼|tw|taiwan|台|新北|彰化/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Taiwan.png' },
    '🇰🇷 韩国': { regex: /韩|🇰🇷|kr|korea|kor|首尔|韓/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Korea.png' },
    '🇩🇪 德国': { regex: /德国|🇩🇪|\bde\b|germany/i, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Germany.png' }
};

// 【修正】定义 rule-providers，确保规则可用
const ruleProviders = {
    BanAD: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/BanAD.list", path: './rulesets/BanAD.yaml', interval: 86400 },
    BanProgramAD: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/BanProgramAD.list", path: './rulesets/BanProgramAD.yaml', interval: 86400 },
    TelegramList: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Telegram.list", path: './rulesets/TelegramList.yaml', interval: 86400 },
    YouTubeList: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/YouTube.list", path: './rulesets/YouTubeList.yaml', interval: 86400 },
    ProxyGFWlist: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/ProxyGFWlist.list", path: './rulesets/ProxyGFWlist.yaml', interval: 86400 },
    UnBan: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/UnBan.list", path: './rulesets/UnBan.yaml', interval: 86400 },
    ChinaDomain: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/ChinaDomain.list", path: './rulesets/ChinaDomain.yaml', interval: 86400 },
    ChinaCompanyIp: { type: 'http', behavior: 'ipcidr', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/ChinaCompanyIp.list", path: './rulesets/ChinaCompanyIp.yaml', interval: 86400 },
    Download: { type: 'http', behavior: 'domain', url: "https://raw.githubusercontent.com/ACL4SSR/ACL4SSR/master/Clash/Download.list", path: './rulesets/Download.yaml', interval: 86400 }
};


module.exports.parse = async (raw, { axios, yaml, console }) => {
    const proxies = yaml.parse(raw).proxies;

    const allProxies = subscriptions.flatMap((sub, index) => {
        const prefix = providerPrefixes[index] || `Sub${index + 1}`;
        return proxies.filter(p => p.sub === sub).map(p => {
            p.name = `[${prefix}] ${p.name}`; return p;
        });
    });

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
    
    const otherProxies = allProxies.filter(p => !matchedProxies.has(p.name)).map(p => p.name);
    groupedProxies['🇺🇳 其他'] = otherProxies;

    const nonEmptyGroups = Object.entries(groupedProxies).filter(([, proxies]) => proxies.length > 0);

    const config = {
        'mixed-port': 7890,
        'allow-lan': true,
        'mode': 'rule',
        'log-level': 'info',
        'external-controller': '127.0.0.1:9090',
        'rule-providers': ruleProviders, // 【修正】将 rule-providers 添加到配置中
        'proxies': allProxies,
        'proxy-groups': [
            { name: '🚀 节点选择', type: 'select', proxies: ['♻️ 自动选择', '🔯 故障转移', ...nonEmptyGroups.map(([name]) => name), 'DIRECT'], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Airport.png'},
            { name: '♻️ 自动选择', type: 'url-test', proxies: allProxies.map(p => p.name), url: testUrl, interval: testInterval, tolerance: 50, lazy: true, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Auto.png' },
            { name: '🔯 故障转移', type: 'fallback', proxies: allProxies.map(p => p.name), url: testUrl, interval: testInterval, lazy: true, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Loop.png' },
            { name: '🌏 直连优选', type: 'fallback', proxies: ['DIRECT', '🚀 节点选择'], url: testUrl, interval: testInterval, lazy: true, icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Global.png'},
            { name: '🎬 Emby', type: 'select', proxies: ['DIRECT', '🚀 节点选择', ...nonEmptyGroups.map(([name]) => name)], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Emby.png' },
            { name: '💬 Telegram', type: 'select', proxies: ['🚀 节点选择', ...nonEmptyGroups.map(([name]) => name)], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/Telegram.png' },
            { name: '📺 YouTube', type: 'select', proxies: ['🚀 节点选择', ...nonEmptyGroups.map(([name]) => name)], icon: 'https://raw.githubusercontent.com/Koolson/Qure/refs/heads/master/IconSet/Color/YouTube.png' },
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
        // 【修正】规则中使用名称引用，而不是 URL
        'rules': [
            "DOMAIN-SUFFIX,lite.cn2gias.uk,🎬 Emby", "DOMAIN-SUFFIX,feiniu.lol,🎬 Emby", "DOMAIN-SUFFIX,ciallo.party,🎬 Emby", "DOMAIN-SUFFIX,liminalnet.com,🎬 Emby", "DOMAIN-SUFFIX,5670320.xyz,🎬 Emby",
            "PROCESS-NAME,com.mountains.hills,DIRECT",
            "DOMAIN-SUFFIX,10520.xyz,DIRECT", "DOMAIN-SUFFIX,jsq.vban.xyz,DIRECT", "DOMAIN-SUFFIX,coemn.com,DIRECT", "DOMAIN-SUFFIX,embycc.link,DIRECT", "DOMAIN-SUFFIX,shrekmedia.org,DIRECT", "DOMAIN-SUFFIX,wenjian.de,DIRECT", "DOMAIN-SUFFIX,hohai.eu.org,DIRECT", "DOMAIN-SUFFIX,cerda.eu.org,DIRECT", "DOMAIN-SUFFIX,seraphine.eu.org,DIRECT", "DOMAIN-SUFFIX,kowo.eu.org,DIRECT", "DOMAIN-SUFFIX,libilibi.eu.org,DIRECT", "DOMAIN-SUFFIX,nouon.eu.org,DIRECT", "DOMAIN-SUFFIX,feiyue.lol,DIRECT", "DOMAIN-SUFFIX,aliz.work,DIRECT", "DOMAIN-SUFFIX,emos.lol,DIRECT", "DOMAIN-SUFFIX,emos.movier.ink,DIRECT", "DOMAIN-SUFFIX,emos.dolby.dpdns.org,DIRECT", "DOMAIN-SUFFIX,bangumi.ca,DIRECT", "DOMAIN-SUFFIX,6666456.xyz,DIRECT", "DOMAIN-SUFFIX,191920.xyz,DIRECT", "DOMAIN-SUFFIX,nijigem.by,DIRECT",
            "RULE-SET,BanAD,REJECT",
            "RULE-SET,BanProgramAD,REJECT",
            "RULE-SET,TelegramList,💬 Telegram",
            "RULE-SET,YouTubeList,📺 YouTube",
            "RULE-SET,ProxyGFWlist,🚀 节点选择",
            "RULE-SET,UnBan,DIRECT",
            "GEOIP,LAN,DIRECT",
            "RULE-SET,ChinaDomain,DIRECT",
            "RULE-SET,ChinaCompanyIp,DIRECT",
            "RULE-SET,Download,DIRECT",
            "GEOIP,CN,DIRECT",
            "MATCH,🌏 直连优选"
        ]
    };
    
    return yaml.stringify(config);
};
