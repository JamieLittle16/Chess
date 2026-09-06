use std::io::{self, BufRead, Write};

use chess_uci::UciSession;

fn main() -> io::Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut output = io::BufWriter::new(stdout.lock());
    let mut session = UciSession::new();

    for line in stdin.lock().lines() {
        let line = line?;
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
