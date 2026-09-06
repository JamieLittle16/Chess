use std::{
    io::{self, BufRead, Write},
    sync::mpsc::{self, Receiver, Sender},
    thread,
};

use chess_uci::UciSession;

fn main() -> io::Result<()> {
    let stdin = io::stdin();
    let (command_tx, command_rx) = mpsc::channel::<String>();

    // The worker remains the sole owner of mutable engine/search state. The input thread retains
    // only the cloneable cancellation token, so `stop` never needs a mutex around the engine.
    let session = UciSession::new_interruptible();
    let stop = session.stop_token();
    let worker = thread::spawn(move || worker_loop(session, command_rx));

    for line in stdin.lock().lines() {
        let line = line?;
        match line.split_whitespace().next() {
            Some("stop") => stop.stop(),
            Some("go") => {
                // Reset before enqueueing, rather than inside the worker, so a subsequent `stop`
                // cannot be lost in the small interval before the worker starts the search.
                stop.reset();
                send_command(&command_tx, line)?;
            }
            Some("quit") => {
                stop.stop();
                send_command(&command_tx, line)?;
                break;
            }
            _ => send_command(&command_tx, line)?,
        }
    }

    // EOF is also a cancellation boundary. Otherwise a depth-only search could outlive stdin and
    // keep the process alive indefinitely while `join` waits.
    stop.stop();
    drop(command_tx);
    worker
        .join()
        .map_err(|_| io::Error::other("UCI worker panicked"))??;
    Ok(())
}

fn send_command(tx: &Sender<String>, line: String) -> io::Result<()> {
    tx.send(line)
        .map_err(|_| io::Error::new(io::ErrorKind::BrokenPipe, "UCI worker exited"))
}

fn worker_loop(mut session: UciSession, commands: Receiver<String>) -> io::Result<()> {
    let stdout = io::stdout();
    let mut output = io::BufWriter::new(stdout.lock());

    for line in commands {
        let response = session.handle_line(&line);
        for response_line in response.lines() {
            writeln!(output, "{response_line}")?;
        }
        output.flush()?;
        if response.should_quit() {
            break;
        }
    }
    Ok(())
}
