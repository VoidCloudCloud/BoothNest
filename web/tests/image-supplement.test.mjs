import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import {ImageSupplement} from '../lib/image-supplement.mjs';
import {safeImage} from '../lib/catalog.mjs';

test('public image overlay fills gaps, replaces archived CDN links and preserves existing media and raw records',async()=>{
 const folder=await mkdtemp(path.join(os.tmpdir(),'boothnest-images-'));let index;
 try{
  const db=new DatabaseSync(path.join(folder,'index.sqlite'));
  db.exec('CREATE TABLE info(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE item_images(id INTEGER PRIMARY KEY,title TEXT,author TEXT,adult INTEGER,images TEXT);');
  db.prepare('INSERT INTO info VALUES(?,?)').run('items','1');
  const archive='/media/boothdex/'+'a'.repeat(40)+'.webp';
  db.prepare('INSERT INTO item_images VALUES(?,?,?,?,?)').run(101,'Sample','Shop',0,JSON.stringify(['https://booth.pximg.net/new.jpg',archive,'https://evil.invalid/x','javascript:x']));db.close();
  const baseline=await readFile(path.join(folder,'index.sqlite'));
  index=await new ImageSupplement(folder).init();assert.equal(index.status().enabled,true);
  const raw={id:101,media:['/media/'+'b'.repeat(32)+'.jpg','https://cdn.vrcatalogue.com/booth/'+'a'.repeat(40)+'.webp'],secret:'preserved'};
  const original=JSON.stringify(raw),next=index.enrich(raw);
  assert.equal(JSON.stringify(raw),original);assert.equal(next.secret,'preserved');
  assert.equal(next.media[0],raw.media[0]);assert.ok(next.media.includes(archive));assert.ok(next.media.includes('/media/boothdex/item/101/0'));
  assert.ok(!next.media.some(url=>url.includes('evil')||url.startsWith('javascript:')||url.includes('cdn.vrcatalogue')));
  assert.deepEqual(index.media(102,['https://booth.pximg.net/original.jpg']),['https://booth.pximg.net/original.jpg']);
  assert.equal(safeImage(archive),archive);assert.equal(safeImage('/media/boothdex/../secret.webp'),'');
  assert.deepEqual(await readFile(path.join(folder,'index.sqlite')),baseline);
 }finally{index?.close();await rm(folder,{recursive:true,force:true});}
});

test('indexed remote previews cache once, reject arbitrary URLs and serve only cached previews while offline',async()=>{
 const folder=await mkdtemp(path.join(os.tmpdir(),'boothnest-image-cache-'));let index,server,calls=0;
 try{
  const db=new DatabaseSync(path.join(folder,'index.sqlite'));db.exec('CREATE TABLE info(key TEXT,value TEXT);CREATE TABLE item_images(id INTEGER,title TEXT,author TEXT,adult INTEGER,images TEXT);');
  db.prepare('INSERT INTO item_images VALUES(?,?,?,?,?)').run(101,'Sample','Shop',0,JSON.stringify(['https://booth.pximg.net/sample.jpg']));db.close();
  index=await new ImageSupplement(folder,{fetcher:async(url,options)=>{calls++;assert.equal(url,'https://booth.pximg.net/sample.jpg');assert.equal(options.credentials,'omit');return new Response('image-test',{headers:{'content-type':'image/jpeg'}});}}).init();
  assert.deepEqual(index.enrich({id:101,media:[]},{offline:true}).media,[]);
  server=http.createServer(async(req,res)=>{if(!await index.serve(req,res,new URL(req.url,'http://localhost').pathname)){res.writeHead(404);res.end();}});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
  const route='/media/boothdex/item/101/0';
  const responses=await Promise.all([fetch(base+route),fetch(base+route)]);for(const response of responses){assert.equal(response.status,200);assert.equal(await response.text(),'image-test');}
  assert.equal(calls,1);assert.deepEqual(index.enrich({id:101,media:[]},{offline:true}).media,[route]);
  assert.equal((await fetch(base+'/media/boothdex/item/999/0')).status,404);assert.equal((await fetch(base+'/media/boothdex/item/101/99')).status,404);assert.equal(calls,1);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));index?.close();await rm(folder,{recursive:true,force:true});}
});

test('archive HTTP routes stream only exact hash filenames and support HEAD without exposing the index',async()=>{
 const folder=await mkdtemp(path.join(os.tmpdir(),'boothnest-image-http-'));let index,server;
 try{
  const db=new DatabaseSync(path.join(folder,'index.sqlite'));db.exec('CREATE TABLE info(key TEXT,value TEXT);CREATE TABLE item_images(id INTEGER,title TEXT,author TEXT,adult INTEGER,images TEXT);');db.close();
  await mkdir(path.join(folder,'images'));await writeFile(path.join(folder,'images','a'.repeat(40)+'.webp'),'RIFF-image-test');
  index=await new ImageSupplement(folder).init();
  server=http.createServer(async(req,res)=>{if(!await index.serve(req,res,new URL(req.url,'http://localhost').pathname)){res.writeHead(404);res.end();}});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
  const route='/media/boothdex/'+'a'.repeat(40)+'.webp';const response=await fetch(base+route);
  assert.equal(response.status,200);assert.equal(response.headers.get('content-type'),'image/webp');assert.equal(await response.text(),'RIFF-image-test');
  const head=await fetch(base+route,{method:'HEAD'});assert.equal(head.status,200);assert.equal(await head.text(),'');
  for(const bad of ['/media/boothdex/index.sqlite','/media/boothdex/%2e%2e/index.sqlite','/media/boothdex/'+'b'.repeat(40)+'.webp'])assert.equal((await fetch(base+bad)).status,404);
 }finally{if(server)await new Promise(resolve=>server.close(resolve));index?.close();await rm(folder,{recursive:true,force:true});}
});

test('missing or malformed optional image index degrades without replacing the catalogue',async()=>{
 const folder=await mkdtemp(path.join(os.tmpdir(),'boothnest-images-missing-'));
 try{
  const missing=await new ImageSupplement(folder).init();assert.equal(missing.enabled,false);assert.deepEqual(missing.media(1,['existing']),['existing']);missing.close();
  await writeFile(path.join(folder,'index.sqlite'),'damaged');const damaged=await new ImageSupplement(folder).init();assert.equal(damaged.enabled,false);assert.ok(damaged.error);damaged.close();
 }finally{await rm(folder,{recursive:true,force:true});}
});
