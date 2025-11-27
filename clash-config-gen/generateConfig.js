const fs = require('fs');
const axios = require('axios');
const yaml = require('js-yaml');

// ==================== 配置区域 ====================
const SUBSCRIPTIONS = [
  {
    name: '丑团1',
    url: 'https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A21?token=ChouLink1'
  },
  {
    name: '丑团2',
    url: 'https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A22?token=ChouLink2'
  },
  {
    name: '丑团3',
    url: 'https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A23?token=ChouLink3'
  },
  {
    name: '丑团4',
    url: 'https://substore.panell.top/share/file/%E4%B8%91%E5%9B%A24?token=ChouLink4'
  }
];

const TEST_URL = 'http://www.gstatic.com/generate_204';
const TEST_INTERVAL = 300;

// 地区过滤规则
const REGION_FILTERS = {
  '🇭🇰 香港': /(?i)港|HK|Hong Kong/i,
  '🇯🇵 日本': /(?i)日本|川日|东京|大阪|泉日|埼玉|沪日|深日|JP|Japan/i,
  '🇸🇬 狮城': /(?i)新加坡|🇸🇬|sg|singapore|坡|狮城/i,
  '🇺🇸 美国': /(?i)^(?!.*(aus|rus)).*(美|🇺🇸|us|usa|american|united states|波特兰|达拉斯|凤凰城|费利蒙|硅谷|拉斯维加斯|洛杉矶|圣何塞|圣克拉拉|西雅图|芝加哥)/i,
  '🇹🇼 湾省': /(?i)台湾|🇹🇼|tw|taiwan|台|新北|彰化/i,
  '🇰🇷 韩国': /(?i)韩|🇰🇷|kr|korea|kor|首尔|韓/i,
  '🇩🇪 德国': /(?i)德国|🇩🇪|\bde\b|germany/i
};

// ==================== 工具函数 ====================

async function fetchSubscription(sub) {
  try {
    console.log(`正在获取订阅: ${sub.name}`);
    const response = await axios.get(sub.url, { 
      timeout: 30000,
      headers: { 'User-Agent': 'clash' }
    });
    
    let data = response.data;
    
    // 处理 base64 编码
    if (typeof data === 'string' && /^[A-Za-z0-9+/=\s]+$/.test(data.trim())) {
      try {
        const buff = Buffer.from(data.trim(), 'base64');
        data = buff.toString('utf8');
      } catch (e) {
        console.log(`${sub.name} 不是 base64 编码，直接解析`);
      }
    }
    
    const config = yaml.load(data);
    
    if (!config.proxies || !Array.isArray(config.proxies)) {
      console.warn(`${sub.name} 没有找到有效的 proxies`);
      return [];
    }
    
    // 给节点添加前缀
    const proxies = config.proxies.map(p => ({
      ...p,
      name: `[${sub.name}] ${p.name}`
    }));
    
    console.log(`${sub.name} 获取到 ${proxies.length} 个节点`);
    return proxies;
    
  } catch (error) {
    console.error(`获取订阅 ${sub.name} 失败:`, error.message);
    return [];
  }
}

function filterProxiesByRegion(proxies, filter) {
  return proxies.filter(p => filter.test(p.name));
}

function createRegionGroups(allProxies) {
  const groups = [];
  
  for (const [name, filter] of Object.entries(REGION_FILTERS)) {
    const regionProxies = filterProxiesByRegion(allProxies, filter);
    
    // 只添加非空分组
    if (regionProxies.length > 0) {
      groups.push({
        name: name,
        type: 'fallback',
        proxies: regionProxies.map(p => p.name),
        url: TEST_URL,
        interval: TEST_INTERVAL,
        lazy: true
      });
    }
  }
  
  return groups;
}

function createOtherGroup(allProxies) {
  const knownRegions = Object.values(REGION_FILTERS);
  const otherProxies = allProxies.filter(p => {
    return !knownRegions.some(filter => filter.test(p.name));
  });
  
  if (otherProxies.length > 0) {
    return {
      name: '🇺🇳 其他',
      type: 'fallback',
      proxies: otherProxies.map(p => p.name),
      url: TEST_URL,
      interval: TEST_INTERVAL,
      lazy: true
    };
  }
  return null;
}

function generateConfig(allProxies, regionGroups) {
  const regionNames = regionGroups.map(g => g.name);
  
  const config = {
    'mixed-port': 7890,
    'allow-lan': true,
    'mode': 'rule',
    'log-level': 'info',
    'external-controller': '127.0.0.1:9090',
    
    proxies: allProxies,
    
    'proxy-groups': [
      {
        name: '🚀 节点选择',
        type: 'select',
        proxies: ['♻️ 自动选择', '🔯 故障转移', ...regionNames, 'DIRECT']
      },
      {
        name: '♻️ 自动选择',
        type: 'url-test',
        proxies: allProxies.map(p => p.name),
        url: TEST_URL,
        interval: TEST_INTERVAL,
        tolerance: 50,
        lazy: true
      },
      {
        name: '🔯 故障转移',
        type: 'fallback',
        proxies: allProxies.map(p => p.name),
        url: TEST_URL,
        interval: TEST_INTERVAL,
        lazy: true
      },
      {
        name: '🌏 直连优选',
        type: 'fallback',
        proxies: ['DIRECT', '🚀 节点选择'],
        url: TEST_URL,
        interval: TEST_INTERVAL,
        lazy: true
      },
      {
        name: '🎬 Emby',
        type: 'select',
        proxies: ['DIRECT', '🚀 节点选择', ...regionNames]
      },
      {
        name: '💬 Telegram',
        type: 'select',
        proxies: ['🚀 节点选择', ...regionNames]
      },
      {
        name: '📺 YouTube',
        type: 'select',
        proxies: ['🚀 节点选择', ...regionNames]
      },
      ...regionGroups
    ],
    
    rules: [
      'DOMAIN-SUFFIX,lite.cn2gias.uk,🎬 Emby',
      'DOMAIN-SUFFIX,feiniu.lol,🎬 Emby',
      'DOMAIN-SUFFIX,ciallo.party,🎬 Emby',
      'DOMAIN-SUFFIX,liminalnet.com,🎬 Emby',
      'DOMAIN-SUFFIX,5670320.xyz,🎬 Emby',
      'GEOIP,LAN,DIRECT',
      'GEOIP,CN,DIRECT',
      'MATCH,🌏 直连优选'
    ]
  };
  
  return config;
}

// ==================== 主函数 ====================

async function main() {
  console.log('==================== 开始生成 Clash 配置 ====================');
  
  // 1. 获取所有订阅
  const allProxiesArrays = await Promise.all(
    SUBSCRIPTIONS.map(sub => fetchSubscription(sub))
  );
  
  const allProxies = allProxiesArrays.flat();
  
  if (allProxies.length === 0) {
    console.error('错误: 未获取到任何有效节点');
    process.exit(1);
  }
  
  console.log(`\n总共获取到 ${allProxies.length} 个节点`);
  
  // 2. 创建地区分组（自动过滤空分组）
  const regionGroups = createRegionGroups(allProxies);
  console.log(`\n生成了 ${regionGroups.length} 个地区分组（已过滤空分组）`);
  
  // 3. 创建"其他"分组
  const otherGroup = createOtherGroup(allProxies);
  if (otherGroup) {
    regionGroups.push(otherGroup);
    console.log('添加了 🇺🇳 其他 分组');
  }
  
  // 4. 生成完整配置
  const config = generateConfig(allProxies, regionGroups);
  
  // 5. 写入文件
  if (!fs.existsSync('dist')) {
    fs.mkdirSync('dist', { recursive: true });
  }
  
  const yamlStr = yaml.dump(config, { 
    lineWidth: -1,
    noRefs: true,
    sortKeys: false
  });
  
  fs.writeFileSync('dist/config.yaml', yamlStr, 'utf8');
  
  console.log('\n==================== 配置生成成功 ====================');
  console.log('文件位置: dist/config.yaml');
  console.log('节点总数:', allProxies.length);
  console.log('分组总数:', config['proxy-groups'].length);
}

main().catch(error => {
  console.error('生成配置时出错:', error);
  process.exit(1);
});
