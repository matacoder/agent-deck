const {defineConfig,devices}=require('@playwright/test');
module.exports=defineConfig({testDir:'.',testMatch:'repo-screenshots.spec.js',workers:1,reporter:'list',outputDir:'/tmp/agent-deck-screenshots',projects:[
 {name:'desktop',use:{browserName:'chromium',viewport:{width:1440,height:900}}},
 {name:'phone',use:{...devices['iPhone 13'],browserName:'webkit'}}
]});
