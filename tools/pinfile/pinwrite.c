/* pinwrite - add rawwrite to the pinprobe no-libc framework.
 * Writes stdin (plaintext) into the PHYSICAL blocks of a pinned file, bypassing
 * FBE encryption. Only writes inside the file's own FIEMAP extents.
 *
 *   pinwrite create PATH SIZE_MB          (create + pin a f2fs file, like pinprobe)
 *   pinwrite rawwrite PATH DEV            (stdin -> physical extents, all blocks)
 *   pinwrite rawreadat PATH DEV OFF LEN   (stdout <- physical extents, read-only)
 *   pinwrite extents PATH [--json]        (same as pinprobe)
 *   pinwrite status PATH
 *
 * Build: aarch64-linux-gnu-gcc -static -nostdlib -no-pie -O2 -o pinwrite pinwrite.c
 */
typedef unsigned long long u64;
typedef unsigned int u32;
typedef long i64;

/* arm64 syscall numbers */
#define SYS_ioctl     29
#define SYS_pread64   67
#define SYS_fallocate 47
#define SYS_pwrite64  68
#define SYS_openat    56
#define SYS_close     57
#define SYS_read      63
#define SYS_write     64
#define SYS_fsync     82
#define SYS_exit      93

#define AT_FDCWD (-100)
#define O_RDWR   2
#define O_CREAT  64
#define O_EXCL   128

#define _IOW(t,nr,sz)  ((u32)((1u<<30)|((sz)<<16)|((t)<<8)|(nr)))
#define _IOR(t,nr,sz)  ((u32)((2u<<30)|((sz)<<16)|((t)<<8)|(nr)))
#define _IOWR(t,nr,sz) ((u32)((3u<<30)|((sz)<<16)|((t)<<8)|(nr)))
#define F2FS_MAGIC 0xf5
#define F2FS_SET_PIN _IOW(F2FS_MAGIC,13,4)
#define F2FS_GET_PIN _IOR(F2FS_MAGIC,14,4)
#define FIEMAP_MAGIC 'f'
#define FIEMAP_IOCTL _IOWR(FIEMAP_MAGIC,11,32)
#define FIEMAP_FLAG_SYNC 1
#define MAX_EXT 8192

struct fext { u64 logical, physical, length, res64[2]; u32 flags, res[3]; };
struct fiemap { u64 start, length; u32 flags, mapped, count, reserved; struct fext ext[MAX_EXT]; };

static long sys6(long n,long a0,long a1,long a2,long a3,long a4,long a5){
  register long x8 __asm__("x8")=n; register long x0 __asm__("x0")=a0;
  register long x1 __asm__("x1")=a1; register long x2 __asm__("x2")=a2;
  register long x3 __asm__("x3")=a3; register long x4 __asm__("x4")=a4;
  register long x5 __asm__("x5")=a5;
  __asm__ volatile("svc #0":"+r"(x0):"r"(x8),"r"(x1),"r"(x2),"r"(x3),"r"(x4),"r"(x5):"memory");
  return x0;
}
static u32 slen(const char*s){u32 n=0;while(s[n])n++;return n;}
static int scmp(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return (unsigned char)*a-(unsigned char)*b;}
static void emitc(char c){sys6(SYS_write,1,(long)&c,1,0,0,0);}
static void puts_(const char*s){sys6(SYS_write,1,(long)s,slen(s),0,0,0);}
static void putd(u64 v){char b[24];int i=0;if(!v){emitc('0');return;}while(v){b[i++]='0'+v%10;v/=10;}while(i>0)emitc(b[--i]);}
static void puth(u64 v){const char*h="0123456789abcdef";char b[18];int i=0;if(!v){puts_("0x0");return;}while(v){b[i++]=h[v&15];v>>=4;}emitc('0');emitc('x');while(i>0)emitc(b[--i]);}
static void zero(volatile void*p,u32 n){volatile unsigned char*b=p;while(n--)*b++=0;}
static u64 atou(const char*s){u64 v=0;while(*s>='0'&&*s<='9'){v=v*10+(u64)(*s-'0');s++;}return v;}
static int err(const char*w,long rc){puts_("pinwrite: ");puts_(w);puts_(" failed rc=");putd((u64)-rc);emitc('\n');return 1;}

static struct fiemap fm; /* global: large, avoid stack */

static int load_extents(const char*path){
  long fd=sys6(SYS_openat,AT_FDCWD,(long)path,O_RDWR,0,0,0);
  if(fd<0)return err("open path",fd);
  zero(&fm,sizeof fm);
  fm.length=~0ULL; fm.flags=FIEMAP_FLAG_SYNC; fm.count=MAX_EXT;
  long rc=sys6(SYS_ioctl,fd,FIEMAP_IOCTL,(long)&fm,0,0,0);
  sys6(SYS_close,fd,0,0,0,0,0);
  if(rc<0)return err("FIEMAP",rc);
  return 0;
}

/* 4096-aligned bounce buffer */
static unsigned char buf[1<<20] __attribute__((aligned(4096)));

/* Create a fresh f2fs pinned file. Size is in even MiB, 2..65536 (same as pinprobe). */
static int cmd_create(const char*path,const char*size_arg){
  u64 mb=atou(size_arg);
  if(mb<2||mb>65536||(mb&1)){puts_("pinwrite: size must be even MiB, 2..65536\n");return 1;}
  long fd=sys6(SYS_openat,AT_FDCWD,(long)path,O_RDWR|O_CREAT|O_EXCL,0600,0,0);
  if(fd<0)return err("open(excl)",fd);
  u32 pin=1;
  long rc=sys6(SYS_ioctl,fd,F2FS_SET_PIN,(long)&pin,0,0,0);
  if(rc<0){sys6(SYS_close,fd,0,0,0,0,0);return err("SET_PIN_FILE",rc);}
  rc=sys6(SYS_fallocate,fd,0,0,(long)(mb<<20),0,0);
  if(rc<0){sys6(SYS_close,fd,0,0,0,0,0);return err("fallocate",rc);}
  sys6(SYS_fsync,fd,0,0,0,0,0);
  sys6(SYS_close,fd,0,0,0,0,0);
  puts_("created ");puts_(path);puts_(" ");putd(mb);puts_(" MiB pinned\n");
  return 0;
}

static int cmd_rawwrite(const char*path,const char*dev){
  int r=load_extents(path); if(r)return r;
  long wfd=sys6(SYS_openat,AT_FDCWD,(long)dev,O_RDWR,0,0,0);
  if(wfd<0)return err("open DEV",wfd);
  u64 written=0;
  u32 n=fm.mapped; if(n>MAX_EXT)n=MAX_EXT;
  for(u32 i=0;i<n;i++){
    u64 phys=fm.ext[i].physical, len=fm.ext[i].length, off=0;
    while(off<len){
      u64 chunk=len-off; if(chunk>sizeof buf)chunk=sizeof buf;
      /* read exactly chunk from stdin */
      u64 got=0;
      while(got<chunk){
        long g=sys6(SYS_read,0,(long)(buf+got),chunk-got,0,0,0);
        if(g<0){sys6(SYS_close,wfd,0,0,0,0,0);return err("read stdin",g);}
        if(g==0)break;
        got+=g;
      }
      if(got==0){sys6(SYS_close,wfd,0,0,0,0,0);goto done;}
      u64 wr=got;
      /* pwrite must be 4096-multiple except possibly last; pad tail */
      if(wr & 4095){u64 pad=(wr+4095)&~4095ULL;zero(buf+wr,pad-wr);wr=pad;}
      long w=sys6(SYS_pwrite64,wfd,(long)buf,wr,phys+off,0,0);
      if(w<0){sys6(SYS_close,wfd,0,0,0,0,0);return err("pwrite",w);}
      written+=got; off+=got;
      if(got<chunk)break; /* stdin EOF */
    }
  }
  sys6(SYS_fsync,wfd,0,0,0,0,0);
done:
  sys6(SYS_close,wfd,0,0,0,0,0);
  puts_("wrote bytes=");putd(written);emitc('\n');
  return 0;
}

/* Read LEN bytes at logical offset OFF of the pinned file from the block device,
 * using the same FIEMAP physical extents. Read-only; needed by tools/shot_fetch.py
 * and ioslog_fetch.py to extract files iOS wrote below FBE. */
static int cmd_rawreadat(const char*path,const char*dev,u64 off,u64 len){
  int r=load_extents(path); if(r)return r;
  long rfd=sys6(SYS_openat,AT_FDCWD,(long)dev,O_RDWR,0,0,0);
  if(rfd<0)return err("open DEV",rfd);
  u64 end=off+len;
  u32 n=fm.mapped; if(n>MAX_EXT)n=MAX_EXT;
  for(u32 i=0;i<n;i++){
    u64 lo=fm.ext[i].logical, phys=fm.ext[i].physical, elen=fm.ext[i].length;
    u64 a=lo>off?lo:off, b=lo+elen<end?lo+elen:end;
    if(a>=b)continue;
    u64 pos=a;
    while(pos<b){
      u64 chunk=b-pos; if(chunk>sizeof buf)chunk=sizeof buf;
      long got=sys6(SYS_pread64,rfd,(long)buf,chunk,phys+(pos-lo),0,0);
      if(got<0){sys6(SYS_close,rfd,0,0,0,0,0);return err("pread64",got);}
      if(got==0)break;
      long wr=sys6(SYS_write,1,(long)buf,(u64)got,0,0,0);
      if(wr<0||(u64)wr!=(u64)got){sys6(SYS_close,rfd,0,0,0,0,0);return err("write stdout",wr<0?wr:-1);}
      pos+=(u64)got;
    }
  }
  sys6(SYS_close,rfd,0,0,0,0,0);
  return 0;
}

static int cmd_status(const char*path){
  long fd=sys6(SYS_openat,AT_FDCWD,(long)path,O_RDWR,0,0,0);
  if(fd<0)return err("open",fd);
  u32 gc=0; long rc=sys6(SYS_ioctl,fd,F2FS_GET_PIN,(long)&gc,0,0,0);
  sys6(SYS_close,fd,0,0,0,0,0);
  if(rc<0)return err("GET_PIN",rc);
  puts_("pin_file=");putd(gc);puts_(" (0=pinned)\n");return 0;
}

static int cmd_extents(const char*path,int json){
  int r=load_extents(path); if(r)return r;
  u32 n=fm.mapped;if(n>MAX_EXT)n=MAX_EXT;
  if(json){
    puts_("{\"file\": \"");puts_(path);puts_("\", \"size\": ");u64 last=0;
    for(u32 i=0;i<n;i++){u64 e=fm.ext[i].logical+fm.ext[i].length;if(e>last)last=e;}
    putd(last);puts_(", \"extents\": [");
    for(u32 i=0;i<n;i++){if(i)emitc(',');emitc('[');putd(fm.ext[i].logical);emitc(',');putd(fm.ext[i].physical);emitc(',');putd(fm.ext[i].length);emitc(',');putd(fm.ext[i].flags);emitc(']');}
    puts_("]}\n");
  } else {
    puts_("logical physical length flags\n");
    for(u32 i=0;i<n;i++){putd(fm.ext[i].logical);emitc(' ');putd(fm.ext[i].physical);emitc(' ');putd(fm.ext[i].length);emitc(' ');puth(fm.ext[i].flags);emitc('\n');}
  }
  puts_("# extents=");putd(n);emitc('\n');return 0;
}

long pinwrite_main(long*sp){
  long argc=sp[0]; char**argv=(char**)(sp+1);
  if(argc<2){puts_("usage: pinwrite create PATH SIZE_MB | rawwrite PATH DEV | rawreadat PATH DEV OFF LEN | extents PATH [--json] | status PATH\n");return 1;}
  if(!scmp(argv[1],"create"))return cmd_create(argv[2],argv[3]);
  if(!scmp(argv[1],"rawwrite"))return cmd_rawwrite(argv[2],argv[3]);
  if(!scmp(argv[1],"rawreadat"))return cmd_rawreadat(argv[2],argv[3],atou(argv[4]),atou(argv[5]));
  if(!scmp(argv[1],"status"))return cmd_status(argv[2]);
  if(!scmp(argv[1],"extents"))return cmd_extents(argv[2],argc>3&&!scmp(argv[3],"--json"));
  puts_("unknown command\n");return 1;
}

__asm__(".global _start\n"
        "_start:\n"
        "  mov x0, sp\n"
        "  bl pinwrite_main\n"
        "  mov x8, #93\n"
        "  svc #0\n");
