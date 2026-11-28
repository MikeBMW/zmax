// IFEO 通用静默转发器
// 注册: HKLM\...\Image File Execution Options\<name>.exe  Debugger = <本 exe 路径>
// 系统调用: ife_wrap.exe "<原 exe 全路径或裸命令名>" <原参数...>
// 作用: 用 CREATE_NO_WINDOW 跑真实程序 —— GUI 父进程调控制台程序时不再产生黑窗。
//
// 编译: csc /nologo /target:winexe /out:<目标>\ife_wrap.exe ife_wrap.cs
// 前提: 真实 exe 已复制到 <root>\_stubs\real\<name>-real.exe  (防 IFEO 递归)
using System;
using System.Diagnostics;
using System.IO;

class IfeWrap
{
    const string REAL_DIR = @"D:\ZMAX\_stubs\real";   // 按需改
    const string LOG_FILE = @"D:\ZMAX\_stubs\ife_hits.log";

    static void Log(string s)
    {
        try
        {
            var fi = new FileInfo(LOG_FILE);
            if (fi.Exists && fi.Length > 512 * 1024) File.WriteAllText(LOG_FILE, "");
            File.AppendAllText(LOG_FILE,
                DateTime.Now.ToString("HH:mm:ss.fff") + " " + s + Environment.NewLine);
        }
        catch { }
    }

    static int Main(string[] args)
    {
        if (args.Length == 0) { Log("no args"); return 2; }
        string real = args[0];
        string[] rest = new string[Math.Max(0, args.Length - 1)];
        if (rest.Length > 0) Array.Copy(args, 1, rest, 0, rest.Length);

        // 防递归: 换成预先复制好的本地副本; 裸命令名(无扩展名)要补 .exe
        try
        {
            string bn = Path.GetFileNameWithoutExtension(real);
            string ext = Path.GetExtension(real);
            if (string.IsNullOrEmpty(ext)) ext = ".exe";
            string alt = Path.Combine(REAL_DIR, bn + "-real" + ext);
            if (File.Exists(alt)) real = alt;
        }
        catch { }

        Log("real=" + real + " args=[" + string.Join("|", rest) + "]");
        if (!File.Exists(real)) { Console.Error.WriteLine("ife_wrap: target not found: " + real); return 3; }

        try
        {
            var psi = new ProcessStartInfo(real, string.Join(" ", rest));
            psi.UseShellExecute = false;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.CreateNoWindow = true;
            psi.WorkingDirectory = Environment.CurrentDirectory;
            using (var p = Process.Start(psi))
            {
                string o = p.StandardOutput.ReadToEnd();
                string e = p.StandardError.ReadToEnd();
                p.WaitForExit();
                Console.Out.Write(o); Console.Out.Flush();
                if (e.Length > 0) { Console.Error.Write(e); Console.Error.Flush(); }
                return p.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ife_wrap failed: " + ex.Message);
            return 1;
        }
    }
}
